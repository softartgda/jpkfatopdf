import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import textwrap
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Stałe konfiguracyjne
SELLER_BANK_ACCOUNT = "Santander (SWIFT: WBKPPLPP), 84 1090 1098 0000 0001 5295 9691"
OUTPUT_DIR = "faktury"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Rejestracja czcionek – upewnij się, że pliki TTF znajdują się w tym samym folderze
pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))

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
        messagebox.showerror("Błąd", f"Nie można wczytać pliku XML: {e}")
        return None

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

# Funkcja generująca pliki PDF na podstawie wybranych faktur
def generate_pdf(seller_name, seller_address, seller_nip, invoices, seller_bank_account, output_mode):
    if output_mode == 'separate':
        for inv in invoices:
            inv_num = inv["number"]
            pdf_filename = f"Faktura_{inv_num.replace('/', '_')}.pdf"
            pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
            c = canvas.Canvas(pdf_path, pagesize=A4)
            draw_invoice(c, inv, seller_name, seller_address, seller_nip, seller_bank_account)
            c.showPage()
            c.save()
        return f"Wygenerowano {len(invoices)} faktur w osobnych plikach PDF w folderze '{OUTPUT_DIR}'."
    else:
        pdf_filename = "Faktury.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        c = canvas.Canvas(pdf_path, pagesize=A4)
        for inv in invoices:
            draw_invoice(c, inv, seller_name, seller_address, seller_nip, seller_bank_account)
            c.showPage()
        c.save()
        return f"Wygenerowano 1 plik PDF zawierający {len(invoices)} faktur w folderze '{OUTPUT_DIR}'."

# Aktualizacja podglądu wybranego pliku – wyświetlenie podstawowych informacji
def update_preview(text_widget, xml_path):
    result = parse_jpk_xml(xml_path)
    if result is None:
        text_widget.delete("1.0", tk.END)
        text_widget.insert(tk.END, "Błąd podczas parsowania pliku XML.")
        return None
    seller_name, seller_address, seller_nip, invoices = result
    preview_text = f"Wybrany plik: {xml_path}\n"
    preview_text += f"Sprzedawca: {seller_name}\n"
    preview_text += f"NIP sprzedawcy: {seller_nip}\n"
    preview_text += f"Adres sprzedawcy: {seller_address}\n"
    preview_text += f"Liczba faktur: {len(invoices)}\n"
    text_widget.delete("1.0", tk.END)
    text_widget.insert(tk.END, preview_text)
    return result

# Funkcja obsługująca wybór pliku
def select_file(text_widget, file_var):
    file_path = filedialog.askopenfilename(
        title="Wybierz plik JPK-29-AN XML",
        filetypes=[("Pliki XML", "*.xml"), ("Wszystkie pliki", "*.*")]
    )
    if file_path:
        file_var.set(file_path)
        update_preview(text_widget, file_path)

# Główny interfejs graficzny
def main_gui():
    root_win = tk.Tk()
    root_win.title("JPKFAK TO PDF Generator")
    root_win.geometry("600x400")

    file_var = tk.StringVar()

    frm = ttk.Frame(root_win, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)

    # Przycisk wyboru pliku
    btn_select = ttk.Button(frm, text="Wybierz plik", command=lambda: select_file(preview_text, file_var))
    btn_select.pack(pady=5)

    # Pole z podglądem zawartości/ustawień pliku
    preview_text = tk.Text(frm, height=10)
    preview_text.pack(fill=tk.BOTH, expand=True, pady=5)

    # Opcje wyboru trybu generowania PDF
    mode_frame = ttk.LabelFrame(frm, text="Tryb generowania PDF")
    mode_frame.pack(pady=5, fill=tk.X)
    mode_var = tk.StringVar(value="separate")
    rb_separate = ttk.Radiobutton(mode_frame, text="Osobne pliki", variable=mode_var, value="separate")
    rb_single = ttk.Radiobutton(mode_frame, text="Jeden plik", variable=mode_var, value="single")
    rb_separate.pack(side=tk.LEFT, padx=10, pady=5)
    rb_single.pack(side=tk.LEFT, padx=10, pady=5)

    # Przycisk generowania PDF
    def on_generate():
        xml_path = file_var.get()
        if not xml_path:
            messagebox.showwarning("Brak pliku", "Najpierw wybierz plik XML.")
            return
        result = parse_jpk_xml(xml_path)
        if result is None:
            return
        seller_name, seller_address, seller_nip, invoices = result
        msg = generate_pdf(seller_name, seller_address, seller_nip, invoices, SELLER_BANK_ACCOUNT, mode_var.get())
        messagebox.showinfo("Sukces", msg)

    btn_generate = ttk.Button(frm, text="Generuj PDF", command=on_generate)
    btn_generate.pack(pady=10)

    root_win.mainloop()

if __name__ == '__main__':
    main_gui()
