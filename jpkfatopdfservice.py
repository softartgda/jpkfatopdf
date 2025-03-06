import os
import io
import shutil
import zipfile
import configparser
import textwrap
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from flask import Flask, request, render_template_string, send_file, flash, redirect, url_for, after_this_request
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Konfiguracja
CONFIG_FILE = "config.ini"
DEFAULT_BANK_ACCOUNT = "Santander (SWIFT: WBKPPLPP), 84 1090 1098 0000 0001 5295 9691"
DEFAULT_OUTPUT_DIR = "faktury"

# Rejestracja czcionek – upewnij się, że pliki TTF są w tym samym folderze
pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))

app = Flask(__name__)
app.secret_key = "supersecretkey"  # wymagane do obsługi flash messages

# Funkcje konfiguracji
def load_config():
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        bank_account = config.get("Settings", "bank_account", fallback=DEFAULT_BANK_ACCOUNT)
    else:
        bank_account = DEFAULT_BANK_ACCOUNT
    return bank_account

def save_config(bank_account):
    config = configparser.ConfigParser()
    config["Settings"] = {"bank_account": bank_account}
    with open(CONFIG_FILE, "w") as configfile:
        config.write(configfile)

# Funkcja rysująca fakturę na stronie PDF
def draw_invoice(c, inv, seller_name, seller_address, seller_nip, seller_bank_account):
    width, height = A4
    c.setFont("DejaVuSans", 10)
    # Dane sprzedawcy
    y_start = height - 50
    c.drawString(50, y_start, "Sprzedawca:")
    seller_info_lines = [
        seller_name,
        seller_address,
        f"NIP: {seller_nip}",
        "",
        "Numer rachunku bankowego:",
        seller_bank_account
    ]
    y = y_start - 15
    for line in seller_info_lines:
        c.drawString(60, y, line)
        y -= 12

    # Dane nabywcy
    c.drawString(320, y_start, "Nabywca:")
    buyer_name_lines = textwrap.wrap(inv["buyer_name"], width=36) if inv["buyer_name"] else [""]
    if len(buyer_name_lines) < 2:
        buyer_name_lines.append("")
    buyer_addr_lines = textwrap.wrap(inv["buyer_addr"], width=36) if inv["buyer_addr"] else [""]
    if len(buyer_addr_lines) < 2:
        buyer_addr_lines.append("")
    buyer_info_lines = buyer_name_lines[:2] + buyer_addr_lines[:2]
    if inv["buyer_nip"]:
        buyer_info_lines.append(f"NIP: {inv['buyer_nip']}")
    y_b = y_start - 15
    for line in buyer_info_lines:
        c.drawString(330, y_b, line)
        y_b -= 12

    # Nagłówek faktury (numer i daty)
    header_y = min(y, y_b) - 20
    c.setFont("DejaVuSans-Bold", 12)
    c.drawString(50, header_y, f"Faktura VAT {inv['number']}")
    c.setFont("DejaVuSans", 10)
    c.drawString(50, header_y - 15, f"Data wystawienia: {inv['date']}")
    c.drawString(50, header_y - 30, f"Data dostawy towarów/wykonania usługi: {inv['date_sell']}")
    if inv["due_date"]:
        c.drawString(50, header_y - 45, f"Termin płatności: {inv['due_date']}")
        c.drawString(50, header_y - 60, "Forma płatności: przelew")

    # Tabela pozycji faktury
    table_y = header_y - 105
    c.setFont("DejaVuSans-Bold", 10)
    c.drawString(50, table_y, "Opis towaru/usługi")
    c.drawString(250, table_y, "Ilość")
    c.drawString(300, table_y, "Jedn.")
    c.drawString(350, table_y, "Netto")
    c.drawString(420, table_y, "VAT 23%")
    c.drawString(480, table_y, "Brutto")
    c.setFont("DejaVuSans", 10)
    line_y = table_y - 15
    for item in inv["lines"]:
        c.drawString(50, line_y, item["desc"])
        c.drawString(250, line_y, item["qty"])
        c.drawString(300, line_y, item["unit"])
        net_str = f"{float(item['net_line']):.2f}"
        vat_str = f"{float(item['vat_line']):.2f}" if item["vat_line"] else ""
        gross_str = f"{float(item['gross_line']):.2f}"
        c.drawRightString(400, line_y, net_str)
        c.drawRightString(450, line_y, vat_str)
        c.drawRightString(540, line_y, gross_str)
        line_y -= 15

    totals_y = line_y - 10
    c.setFont("DejaVuSans-Bold", 10)
    c.drawString(300, totals_y, "Suma netto PLN:")
    c.drawString(300, totals_y - 15, "Suma VAT 23% PLN:")
    c.drawString(300, totals_y - 30, "Suma brutto PLN:")
    c.setFont("DejaVuSans", 10)
    c.drawRightString(540, totals_y, f"{float(inv['net_total']):.2f}")
    c.drawRightString(540, totals_y - 15, f"{float(inv['vat_total']):.2f}")
    c.drawRightString(540, totals_y - 30, f"{float(inv['gross_total']):.2f}")

# Funkcja parsująca plik XML JPK-29-AN
def parse_jpk_xml(xml_path):
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        raise Exception(f"Nie można wczytać pliku XML: {e}")

    ns = {
        "jp": "http://jpk.mf.gov.pl/wzor/2022/02/17/02171/",
        "etd": "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2018/08/24/eD/DefinicjeTypy/"
    }

    # Dane sprzedawcy
    seller_name = None
    seller_address = None
    seller_nip = None

    podmiot = root.find("jp:Podmiot1", ns)
    if podmiot is not None:
        nip_elem = podmiot.find("jp:IdentyfikatorPodmiotu/jp:NIP", ns)
        name_elem = podmiot.find("jp:IdentyfikatorPodmiotu/jp:PelnaNazwa", ns)
        addr_elem = podmiot.find("jp:AdresPodmiotu", ns)
        if nip_elem is not None:
            seller_nip = nip_elem.text
        if name_elem is not None:
            seller_name = name_elem.text
        if addr_elem is not None:
            country = addr_elem.find("etd:KodKraju", ns)
            street = addr_elem.find("etd:Ulica", ns)
            bld = addr_elem.find("etd:NrDomu", ns)
            unit = addr_elem.find("etd:NrLokalu", ns)
            city = addr_elem.find("etd:Miejscowosc", ns)
            postcode = addr_elem.find("etd:KodPocztowy", ns)
            addr_parts = []
            if street is not None:
                addr_parts.append(street.text + (" " + bld.text if bld is not None else "") + ("/" + unit.text if unit is not None else ""))
            if postcode is not None and city is not None:
                addr_parts.append(postcode.text + " " + city.text)
            seller_address = ", ".join(addr_parts)
            if country is not None and country.text and country.text.upper() != "PL":
                seller_address += ", " + country.text

    invoices = []
    for faktura in root.findall("jp:Faktura", ns):
        inv_number = faktura.find("jp:P_2A", ns).text
        issue_date = faktura.find("jp:P_1", ns).text
        sell_date = faktura.find("jp:P_6", ns).text
        buyer_name = faktura.find("jp:P_3A", ns).text
        buyer_addr = faktura.find("jp:P_3B", ns).text
        if seller_name is None:
            seller_name = faktura.find("jp:P_3C", ns).text
        if seller_address is None:
            seller_address = faktura.find("jp:P_3D", ns).text
        if seller_nip is None:
            seller_nip = faktura.find("jp:P_4B", ns).text
        buyer_nip_elem = faktura.find("jp:P_5B", ns)
        buyer_nip = buyer_nip_elem.text if buyer_nip_elem is not None else ""
        net_total = faktura.find("jp:P_13_1", ns).text
        vat_total = faktura.find("jp:P_14_1", ns).text
        gross_total = faktura.find("jp:P_15", ns).text
        try:
            issue_dt = datetime.strptime(issue_date, "%Y-%m-%d")
            due_date = (issue_dt + timedelta(days=7)).strftime("%Y-%m-%d")
        except Exception:
            due_date = ""

        invoices.append({
            "number": inv_number,
            "date": issue_date,
            "date_sell": sell_date,
            "due_date": due_date,
            "buyer_name": buyer_name,
            "buyer_addr": buyer_addr,
            "buyer_nip": buyer_nip,
            "net_total": net_total,
            "vat_total": vat_total,
            "gross_total": gross_total,
            "lines": []
        })

    for line in root.findall("jp:FakturaWiersz", ns):
        inv_num = line.find("jp:P_2B", ns).text
        desc = line.find("jp:P_7", ns).text
        unit = line.find("jp:P_8A", ns).text
        qty = line.find("jp:P_8B", ns).text
        net_line = line.find("jp:P_11", ns).text
        gross_line = line.find("jp:P_11A", ns).text
        try:
            vat_line = f"{(float(gross_line) - float(net_line)):.2f}"
        except:
            vat_line = ""
        for inv in invoices:
            if inv["number"] == inv_num:
                inv["lines"].append({
                    "desc": desc,
                    "qty": qty,
                    "unit": unit,
                    "net_line": net_line,
                    "vat_line": vat_line,
                    "gross_line": gross_line
                })
                break

    return seller_name, seller_address, seller_nip, invoices

# Funkcja generująca PDF – zapisuje pliki w podanym folderze tymczasowym
# Dla trybu 'single' zwraca ścieżkę do jednego pliku, dla 'separate' generuje wiele plików.
def generate_pdf(seller_name, seller_address, seller_nip, invoices, seller_bank_account, output_mode, output_dir):
    if output_mode == 'separate':
        for inv in invoices:
            inv_num = inv["number"]
            pdf_filename = f"Faktura_{inv_num.replace('/', '_')}.pdf"
            pdf_path = os.path.join(output_dir, pdf_filename)
            c = canvas.Canvas(pdf_path, pagesize=A4)
            draw_invoice(c, inv, seller_name, seller_address, seller_nip, seller_bank_account)
            c.showPage()
            c.save()
        return None  # w tym przypadku będziemy zipować cały folder
    else:
        pdf_filename = "Faktury.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
        c = canvas.Canvas(pdf_path, pagesize=A4)
        for inv in invoices:
            draw_invoice(c, inv, seller_name, seller_address, seller_nip, seller_bank_account)
            c.showPage()
        c.save()
        return pdf_path

# Funkcja zipująca zawartość katalogu (wszystkie wygenerowane pliki PDF) do archiwum ZIP w pamięci
def zip_directory(directory):
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root_dir, _, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root_dir, file)
                arcname = os.path.relpath(file_path, directory)
                zf.write(file_path, arcname)
    memory_file.seek(0)
    return memory_file

# Szablon HTML (używamy render_template_string, aby mieć wszystko w jednym pliku)
HTML_TEMPLATE = """
<!doctype html>
<html lang="pl">
  <head>
    <meta charset="utf-8">
    <title>JPK - FAKTO PDF Generator</title>
  </head>
  <body>
    <h1>JPK - FAKTO PDF Generator</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <ul style="color: red;">
          {% for msg in messages %}
            <li>{{ msg }}</li>
          {% endfor %}
        </ul>
      {% endif %}
    {% endwith %}
    <form method="post" enctype="multipart/form-data">
      <label>Wybierz plik JPK-29-AN XML:</label><br>
      <input type="file" name="xml_file" accept=".xml" required><br><br>

      <label>Numer rachunku bankowego:</label><br>
      <input type="text" name="bank_account" value="{{ bank_account }}" size="80"><br><br>

      <label>Folder wyjściowy:</label><br>
      <input type="text" name="output_folder" value="{{ output_folder }}" size="80"><br><br>

      <label>Tryb generowania PDF:</label><br>
      <input type="radio" id="separate" name="mode" value="separate" checked>
      <label for="separate">Osobne pliki</label><br>
      <input type="radio" id="single" name="mode" value="single">
      <label for="single">Jeden plik</label><br><br>

      <input type="submit" value="Generuj PDF">
    </form>
  </body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(HTML_TEMPLATE, bank_account=load_config(), output_folder=DEFAULT_OUTPUT_DIR)
    else:
        # Pobranie danych z formularza
        if "xml_file" not in request.files:
            flash("Brak pliku XML.")
            return redirect(request.url)
        xml_file = request.files["xml_file"]
        if xml_file.filename == "":
            flash("Nie wybrano pliku.")
            return redirect(request.url)
        bank_account = request.form.get("bank_account", DEFAULT_BANK_ACCOUNT).strip()
        output_folder = request.form.get("output_folder", DEFAULT_OUTPUT_DIR).strip()
        mode = request.form.get("mode", "separate")

        # Zapisanie konfiguracji (numer rachunku)
        save_config(bank_account)

        # Utworzenie folderu wyjściowego (jeśli nie istnieje) oraz podfolderu tymczasowego
        os.makedirs(output_folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        temp_dir = os.path.join(output_folder, f"temp_{timestamp}")
        os.makedirs(temp_dir, exist_ok=True)

        # Zapisanie przesłanego pliku XML do tymczasowego folderu
        xml_path = os.path.join(temp_dir, "input.xml")
        xml_file.save(xml_path)

        try:
            seller_name, seller_address, seller_nip, invoices = parse_jpk_xml(xml_path)
        except Exception as e:
            flash(str(e))
            shutil.rmtree(temp_dir)
            return redirect(request.url)

        result = generate_pdf(seller_name, seller_address, seller_nip, invoices, bank_account, mode, temp_dir)

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                app.logger.error("Błąd przy usuwaniu katalogu tymczasowego: %s", e)
            return response

        if mode == "single":
            # W trybie 'single' zwracamy wygenerowany plik PDF
            if result is None or not os.path.exists(result):
                flash("Wystąpił błąd przy generowaniu pliku PDF.")
                return redirect(request.url)
            return send_file(result, as_attachment=True, download_name=os.path.basename(result))
        else:
            # W trybie 'separate' zipujemy zawartość katalogu tymczasowego
            zip_file = zip_directory(temp_dir)
            return send_file(zip_file, as_attachment=True, download_name=f"faktury_{timestamp}.zip")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
