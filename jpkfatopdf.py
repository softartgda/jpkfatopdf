import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- Configuration ---
xml_path = "JPK-29-AN-202501.xml"  # Path to the JPK_FA(4) XML file (update this as needed)
output_dir = "faktury"
seller_bank_account = "Santander (SWIFT: WBKPPLPP), 84 1090 1098 0000 0001 5295 9691"  # Seller’s bank account number

# Parse XML with namespace handling
tree = ET.parse(xml_path)
root = tree.getroot()
# ns = {"jp": root.tag.split("}")[0].strip("{")}  # namespace dictionary, e.g., {'jp': 'http://jpk.mf.gov.pl/wzor/2022/02/17/02171/'}
ns = {
    "jp": "http://jpk.mf.gov.pl/wzor/2022/02/17/02171/",
    "etd": "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2018/08/24/eD/DefinicjeTypy/"
}
# Extract seller's name, address, and NIP from the first invoice or Podmiot1 (assuming one seller for all invoices)
seller_name = None
seller_address = None
seller_nip = None

# Option 1: Use Podmiot1 section for seller info if present
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
        # Build a single-line address from the address components
        country = addr_elem.find("etd:KodKraju", ns)  # ns might need 'etd' for the address namespace
        street = addr_elem.find("etd:Ulica", ns)
        bld = addr_elem.find("etd:NrDomu", ns)
        unit = addr_elem.find("etd:NrLokalu", ns)
        city = addr_elem.find("etd:Miejscowosc", ns)
        postcode = addr_elem.find("etd:KodPocztowy", ns)
        # Combine parts (ignoring None values)
        addr_parts = []
        if street is not None: addr_parts.append(street.text + (" " + bld.text if bld is not None else "") + ("/" + unit.text if unit is not None else ""))
        if postcode is not None and city is not None:
            addr_parts.append(postcode.text + " " + city.text)
        seller_address = ", ".join(addr_parts)
        # Include country if not Poland (PL)
        if country is not None and country.text and country.text.upper() != "PL":
            seller_address += ", " + country.text

# If Podmiot1 not available or incomplete, fallback to first invoice seller fields
invoices = []
for faktura in root.findall("jp:Faktura", ns):
    inv_number = faktura.find("jp:P_2A", ns).text  # Invoice number
    issue_date = faktura.find("jp:P_1", ns).text   # Issue date (YYYY-MM-DD)
    sell_date = faktura.find("jp:P_6", ns).text   # Issue date (YYYY-MM-DD)
    buyer_name = faktura.find("jp:P_3A", ns).text  # Buyer name
    buyer_addr = faktura.find("jp:P_3B", ns).text  # Buyer address (single string)
    # Seller details (may repeat for each invoice)
    if seller_name is None:
        seller_name = faktura.find("jp:P_3C", ns).text  # Seller name
    if seller_address is None:
        seller_address = faktura.find("jp:P_3D", ns).text  # Seller address
    if seller_nip is None:
        seller_nip = faktura.find("jp:P_4B", ns).text      # Seller NIP
    buyer_nip_elem = faktura.find("jp:P_5B", ns)           # Buyer NIP
    buyer_nip = buyer_nip_elem.text if buyer_nip_elem is not None else ""
    # Invoice totals (as strings, no currency symbol in XML)
    net_total = faktura.find("jp:P_13_1", ns).text  # assuming standard rate net
    vat_total = faktura.find("jp:P_14_1", ns).text  # assuming standard rate VAT
    gross_total = faktura.find("jp:P_15", ns).text
    # Compute payment due date (7 days from issue_date)
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d")
        due_date = (issue_dt + timedelta(days=7)).strftime("%Y-%m-%d")
    except Exception as e:
        due_date = ""  # if date format is unexpected, leave blank

    # Prepare invoice record
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
        "lines": []  # to fill later
    })

# Collect all invoice lines and attach to the corresponding invoice
for line in root.findall("jp:FakturaWiersz", ns):
    inv_num = line.find("jp:P_2B", ns).text  # invoice number reference
    desc = line.find("jp:P_7", ns).text      # item description
    unit = line.find("jp:P_8A", ns).text     # unit of measure
    qty = line.find("jp:P_8B", ns).text      # quantity (as string, could convert to int/float if needed)
    net_price = line.find("jp:P_9A", ns).text   # net unit price
    gross_price = line.find("jp:P_9B", ns).text # gross unit price
    net_line = line.find("jp:P_11", ns).text    # net amount for this line (net_price * qty)
    gross_line = line.find("jp:P_11A", ns).text # gross amount for this line
    # Calculate VAT for line (gross - net)
    try:
        vat_line = f"{(float(gross_line) - float(net_line)):.2f}"
    except:
        vat_line = ""  # in case of parse error
    # Find the corresponding invoice and add this line
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

# Create output directory if not exists
os.makedirs(output_dir, exist_ok=True)

# Generate PDF for each invoice
for inv in invoices:
    inv_num = inv["number"]
    # Prepare PDF file path (replace slashes in invoice number with underscores)
    pdf_filename = f"Faktura_{inv_num.replace('/', '_')}.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)

    # Initialize PDF canvas
    
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))

    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4  # width=595, height=842 points for A4
    
    # Set fonts (optional): e.g., c.setFont("Helvetica", 10)
    c.setFont("DejaVuSans", 10)

    # Top-left section: Seller details
    y_start = height - 50  # start 50 points from top
    c.drawString(50, y_start, "Sprzedawca:")
    seller_info_lines = [
        seller_name,
        seller_address,
        f"NIP: {seller_nip}",
        f"Numer rachunku bankowego:",
        f"{seller_bank_account}"
    ]
    y = y_start - 15
    for line in seller_info_lines:
        c.drawString(60, y, line)
        y -= 12

    # Top-right section: Buyer details
    c.drawString(320, y_start, "Nabywca:")
    buyer_info_lines = [
        inv["buyer_name"],
        inv["buyer_addr"],
        f"NIP: {inv['buyer_nip']}" if inv["buyer_nip"] else ""
    ]
    y_b = y_start - 15
    for line in buyer_info_lines:
        c.drawString(330, y_b, line)
        y_b -= 12

    # Invoice header (number and dates) below seller/buyer
    header_y = min(y, y_b) - 20  # start below whichever is lower
    c.setFont("DejaVuSans-Bold", 12)
    c.drawString(50, header_y, f"Faktura VAT {inv_num}")
    c.setFont("DejaVuSans", 10)
    c.drawString(50, header_y - 15, f"Data wystawienia: {inv['date']}")
    c.drawString(50, header_y - 30, f"Data dostawy towarów/wykonania usługi: {inv['date_sell']}")
    if inv["due_date"]:
        c.drawString(50, header_y - 45, f"Termin płatności: {inv['due_date']}")

    # Line items table header
    table_y = header_y - 75
    c.setFont("DejaVuSans-Bold", 10)
    c.drawString(50, table_y, "Opis towaru/usługi")
    c.drawString(250, table_y, "Ilość")
    c.drawString(300, table_y, "Jedn.")   # unit
    c.drawString(350, table_y, "Netto")   # net
    c.drawString(420, table_y, "VAT")
    c.drawString(470, table_y, "Brutto")  # gross
    c.setFont("DejaVuSans", 10)
    # Draw each line item
    line_y = table_y - 15
    for item in inv["lines"]:
        c.drawString(50, line_y, item["desc"])
        c.drawString(250, line_y, item["qty"])
        c.drawString(300, line_y, item["unit"])
        # Right-align numeric values by computing text width (for better alignment)
        net_str = f"{float(item['net_line']):.2f}"
        vat_str = f"{float(item['vat_line']):.2f}" if item["vat_line"] else ""
        gross_str = f"{float(item['gross_line']):.2f}"
        # Draw numbers a bit right-shifted
        c.drawRightString(400, line_y, net_str)
        c.drawRightString(450, line_y, vat_str)
        c.drawRightString(540, line_y, gross_str)
        line_y -= 15

    # Totals (net, VAT, gross) at bottom of item table
    totals_y = line_y - 10
    c.setFont("DejaVuSans-Bold", 10)
    c.drawString(300, totals_y, "Suma netto PLN:")
    c.drawString(300, totals_y - 15, "Suma VAT PLN:")
    c.drawString(300, totals_y - 30, "Suma brutto PLN:")
    c.setFont("DejaVuSans", 10)
    c.drawRightString(540, totals_y, f"{float(inv['net_total']):.2f}")
    c.drawRightString(540, totals_y - 15, f"{float(inv['vat_total']):.2f}")
    c.drawRightString(540, totals_y - 30, f"{float(inv['gross_total']):.2f}")

    # Add a note (if needed) or footer – e.g., "Thank you" or payment info
    # (Skipping detailed footer for brevity)

    # Finalize PDF
    c.showPage()
    c.save()

print(f"Generated {len(invoices)} invoice PDFs in folder '{output_dir}'.")
