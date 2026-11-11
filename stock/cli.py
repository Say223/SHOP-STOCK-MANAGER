"""Interface en ligne de commande."""
import argparse
import sys
import webbrowser
from pathlib import Path

from .db import connect
from .purchasing import PurchasingService
from .report import build_report
from .service import StockError, StockService

STATUS_LABEL = {"draft": "brouillon", "sent": "envoyée", "received": "reçue", "cancelled": "annulée"}


def money(v):
    return f"{v:,.2f} €".replace(",", " ")


def print_products(rows):
    if not rows:
        print("Aucun produit.")
        return
    print(f"{'REF':<10}{'NOM':<24}{'PRIX':>12}{'QTÉ':>7}{'SEUIL':>7}  ALERTE")
    print("-" * 70)
    for r in rows:
        alert = "⚠ réapprovisionner" if r["quantity"] <= r["min_stock"] else ""
        print(f"{r['sku']:<10}{r['name'][:22]:<24}{money(r['price']):>12}{r['quantity']:>7}{r['min_stock']:>7}  {alert}")


def print_orders(rows, purchasing):
    if not rows:
        print("Aucune commande.")
        return
    print(f"{'N°':<5}{'FOURNISSEUR':<20}{'STATUT':<12}{'MONTANT':>14}  CRÉÉE LE")
    print("-" * 68)
    for o in rows:
        sup = purchasing.get_supplier(o["supplier_id"])["name"]
        print(f"{o['id']:<5}{sup[:18]:<20}{STATUS_LABEL[o['status']]:<12}"
              f"{money(purchasing.order_total(o['id'])):>14}  {o['created_at']}")


def build_parser():
    p = argparse.ArgumentParser(prog="stock", description="Gestion de stock et réapprovisionnement")
    p.add_argument("--db", default="stock.db", help="fichier SQLite (défaut : stock.db)")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="ajouter un produit")
    a.add_argument("sku"); a.add_argument("name"); a.add_argument("price", type=float)
    a.add_argument("--qty", type=int, default=0)
    a.add_argument("--min", type=int, default=5, dest="min_stock")
    a.add_argument("--supplier", type=int, default=None, help="id du fournisseur")

    sub.add_parser("list", help="lister les produits")
    ss = sub.add_parser("set-supplier", help="rattacher un produit à un fournisseur")
    ss.add_argument("sku"); ss.add_argument("supplier_id", type=int)

    for name, sign in (("in", 1), ("out", -1)):
        s = sub.add_parser(name, help="entrée de stock" if sign > 0 else "sortie de stock")
        s.add_argument("sku"); s.add_argument("qty", type=int)
        s.add_argument("--reason", default="Entrée" if sign > 0 else "Sortie")
        s.set_defaults(sign=sign)

    sub.add_parser("low", help="produits sous le seuil d'alerte")
    sub.add_parser("value", help="valeur totale du stock")
    h = sub.add_parser("history", help="historique des mouvements d'un produit"); h.add_argument("sku")
    d = sub.add_parser("delete", help="supprimer un produit"); d.add_argument("sku")
    e = sub.add_parser("export", help="exporter en CSV"); e.add_argument("file", nargs="?", default="stock_export.csv")

    sa = sub.add_parser("supplier-add", help="ajouter un fournisseur")
    sa.add_argument("name"); sa.add_argument("--email", default=""); sa.add_argument("--lead-days", type=int, default=7)
    sub.add_parser("suppliers", help="lister les fournisseurs")

    pn = sub.add_parser("po-new", help="créer une commande fournisseur (brouillon)"); pn.add_argument("supplier_id", type=int)
    pa = sub.add_parser("po-add", help="ajouter une ligne à une commande en brouillon")
    pa.add_argument("po_id", type=int); pa.add_argument("sku"); pa.add_argument("qty", type=int)
    pa.add_argument("--cost", type=float, default=None, help="coût unitaire (défaut : prix du produit)")
    for name, helptxt in (("po-send", "envoyer la commande"), ("po-receive", "réceptionner (entre en stock)"),
                          ("po-cancel", "annuler la commande"), ("po-show", "détail d'une commande")):
        x = sub.add_parser(name, help=helptxt); x.add_argument("po_id", type=int)
    pl = sub.add_parser("po-list", help="lister les commandes")
    pl.add_argument("--status", choices=list(STATUS_LABEL), default=None)

    sub.add_parser("reorder", help="suggérer les réapprovisionnements")
    ro = sub.add_parser("reorder-create", help="créer des brouillons de commande à partir des suggestions")
    ro.set_defaults(create=True)
    sub.add_parser("demo", help="charger des données de démonstration")
    rp = sub.add_parser("report", help="générer un rapport HTML (stock, alertes, commandes)")
    rp.add_argument("--output", default="output/stock_report.html", help="fichier HTML de sortie")
    rp.add_argument("--open", action="store_true", help="ouvrir le rapport dans le navigateur")
    return p


def run(args, stock, purchasing):
    c = args.command
    if c == "add":
        p = stock.add_product(args.sku, args.name, args.price, args.qty, args.min_stock, args.supplier)
        print(f"Produit ajouté : {p['sku']} - {p['name']}")
    elif c == "list":
        print_products(stock.list_products())
    elif c == "set-supplier":
        stock.set_supplier(args.sku, args.supplier_id)
        print("Fournisseur rattaché.")
    elif c in ("in", "out"):
        if args.qty <= 0:
            raise StockError("La quantité doit être strictement positive.")
        p = stock.move_stock(args.sku, args.sign * args.qty, args.reason)
        print(f"{p['sku']} : nouveau stock = {p['quantity']}")
    elif c == "low":
        print_products(stock.low_stock())
    elif c == "value":
        print(f"Valeur totale du stock : {money(stock.total_value())}")
    elif c == "history":
        for m in stock.history(args.sku):
            print(f"{m['created_at']}  {m['delta']:+d}  {m['reason']}")
    elif c == "delete":
        stock.delete_product(args.sku)
        print("Produit supprimé.")
    elif c == "export":
        print(f"{stock.export_csv(args.file)} produit(s) exporté(s) vers {args.file}")
    elif c == "supplier-add":
        s = purchasing.add_supplier(args.name, args.email, args.lead_days)
        print(f"Fournisseur #{s['id']} créé : {s['name']}")
    elif c == "suppliers":
        rows = purchasing.list_suppliers()
        if not rows:
            print("Aucun fournisseur.")
        for s in rows:
            print(f"#{s['id']:<3}{s['name']:<20}{s['email']:<32}délai : {s['lead_days']} j")
    elif c == "po-new":
        o = purchasing.create_order(args.supplier_id)
        print(f"Commande #{o['id']} créée (brouillon).")
    elif c == "po-add":
        purchasing.add_line(args.po_id, args.sku, args.qty, args.cost)
        print(f"Ligne ajoutée à la commande #{args.po_id}.")
    elif c == "po-send":
        purchasing.send_order(args.po_id)
        print(f"Commande #{args.po_id} envoyée.")
    elif c == "po-receive":
        purchasing.receive_order(args.po_id)
        print(f"Commande #{args.po_id} réceptionnée : stock mis à jour.")
    elif c == "po-cancel":
        purchasing.cancel_order(args.po_id)
        print(f"Commande #{args.po_id} annulée.")
    elif c == "po-show":
        o = purchasing.get_order(args.po_id)
        sup = purchasing.get_supplier(o["supplier_id"])
        print(f"Commande #{o['id']} - {sup['name']} - {STATUS_LABEL[o['status']]}")
        for l in purchasing.order_lines(o["id"]):
            print(f"  {l['sku']:<10}{l['name'][:22]:<24}{l['quantity']:>5} x {money(l['unit_cost'])}")
        print(f"  Total : {money(purchasing.order_total(o['id']))}")
    elif c == "po-list":
        print_orders(purchasing.list_orders(args.status), purchasing)
    elif c == "reorder":
        sug = purchasing.suggest_reorder()
        if not sug:
            print("Aucun réapprovisionnement nécessaire.")
        for s in sug:
            sup = f"fournisseur #{s['supplier_id']}" if s["supplier_id"] else "⚠ sans fournisseur"
            print(f"{s['sku']:<10}{s['name'][:22]:<24}stock {s['quantity']:>4}  ->  commander {s['suggested']:>4}  ({sup})")
    elif c == "reorder-create":
        created, without = purchasing.create_orders_from_suggestions()
        print(f"Brouillons créés/mis à jour : {created if created else 'aucun'}")
        if without:
            print(f"Produits sans fournisseur (non commandés) : {', '.join(without)}")
    elif c == "demo":
        print(f"{purchasing.seed_demo()} produit(s) de démonstration ajouté(s).")
    elif c == "report":
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_report(stock, purchasing), encoding="utf-8")
        print(f"Rapport généré : {out.resolve()}")
        if args.open:
            webbrowser.open(out.resolve().as_uri())


def main(argv=None):
    args = build_parser().parse_args(argv)
    conn = connect(args.db)
    try:
        run(args, StockService(conn), PurchasingService(conn))
    except StockError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0

