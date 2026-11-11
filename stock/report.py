"""Rapport HTML autonome sur l'état du stock et des commandes (aucune librairie externe)."""
from datetime import datetime
from html import escape

STATUS_LABEL = {"draft": "Brouillon", "sent": "Envoyée", "received": "Reçue", "cancelled": "Annulée"}


def money(v):
    return f"{v:,.2f} €".replace(",", " ")


def _stock_bar(quantity, min_stock):
    """Barre de niveau de stock : rouge sous le seuil, verte au-dessus ; le trait marque le seuil."""
    scale = max(quantity, min_stock * 2, 1)
    width = min(100.0, quantity / scale * 100)
    marker = min(100.0, min_stock / scale * 100)
    color = "#dc2626" if quantity <= min_stock else "#16a34a"
    return (f'<div class="bar"><div class="fill" style="width:{width:.0f}%;background:{color}"></div>'
            f'<div class="mark" style="left:{marker:.0f}%"></div></div>')


def build_report(stock, purchasing, title="Rapport de stock"):
    products = stock.list_products()
    low = stock.low_stock()
    orders = purchasing.list_orders()
    open_orders = [o for o in orders if o["status"] in ("draft", "sent")]
    suppliers = {s["id"]: s["name"] for s in purchasing.list_suppliers()}

    cards = [
        ("Produits suivis", str(len(products))),
        ("Valeur du stock", money(stock.total_value())),
        ("Produits à réapprovisionner", str(len(low))),
        ("Commandes en cours", str(len(open_orders))),
    ]
    cards_html = "".join(
        f'<div class="card{" warn" if label.startswith("Produits à") and low else ""}">'
        f'<span>{escape(label)}</span><strong>{escape(value)}</strong></div>' for label, value in cards)

    product_rows = "".join(
        f"<tr><td>{escape(p['sku'])}</td><td>{escape(p['name'])}</td>"
        f"<td class='num'>{money(p['price'])}</td><td class='num'>{p['quantity']}</td>"
        f"<td class='num'>{p['min_stock']}</td><td class='level'>{_stock_bar(p['quantity'], p['min_stock'])}</td>"
        f"<td>{escape(suppliers.get(p['supplier_id'], '—'))}</td></tr>"
        for p in products) or "<tr><td colspan='7'>Aucun produit.</td></tr>"

    suggestions = purchasing.suggest_reorder()
    sug_rows = "".join(
        f"<tr><td>{escape(s['sku'])}</td><td>{escape(s['name'])}</td><td class='num'>{s['quantity']}</td>"
        f"<td class='num'><strong>{s['suggested']}</strong></td>"
        f"<td>{escape(suppliers.get(s['supplier_id'], '⚠ sans fournisseur'))}</td></tr>"
        for s in suggestions) or "<tr><td colspan='5'>Aucun réapprovisionnement nécessaire.</td></tr>"

    order_rows = "".join(
        f"<tr><td>#{o['id']}</td><td>{escape(suppliers.get(o['supplier_id'], '?'))}</td>"
        f"<td><span class='tag {o['status']}'>{STATUS_LABEL[o['status']]}</span></td>"
        f"<td class='num'>{money(purchasing.order_total(o['id']))}</td><td>{escape(o['created_at'])}</td></tr>"
        for o in orders) or "<tr><td colspan='5'>Aucune commande.</td></tr>"

    move_rows = "".join(
        f"<tr><td>{escape(m['created_at'])}</td><td>{escape(m['sku'])}</td>"
        f"<td class='num {'pos' if m['delta'] > 0 else 'neg'}'>{m['delta']:+d}</td><td>{escape(m['reason'])}</td></tr>"
        for m in stock.recent_movements(10)) or "<tr><td colspan='4'>Aucun mouvement.</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>{escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f3f4f6;color:#111827;margin:0;padding:24px}}
main{{max-width:1000px;margin:auto}} h1{{margin-bottom:4px}} .sub{{color:#6b7280;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}}
.card{{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px #0002}}
.card span{{display:block;color:#6b7280;font-size:13px}} .card strong{{font-size:24px}} .card.warn strong{{color:#dc2626}}
section{{background:#fff;border-radius:10px;padding:16px 20px;margin-bottom:20px;box-shadow:0 1px 3px #0002;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{padding:8px;border-bottom:1px solid #e5e7eb;text-align:left}}
.num{{text-align:right;white-space:nowrap}} .pos{{color:#15803d}} .neg{{color:#b91c1c}}
.level{{min-width:140px}} .bar{{position:relative;height:12px;background:#e5e7eb;border-radius:6px}}
.fill{{height:12px;border-radius:6px}} .mark{{position:absolute;top:-3px;width:2px;height:18px;background:#111827}}
.tag{{padding:2px 8px;border-radius:10px;font-size:12px;background:#e5e7eb}}
.tag.draft{{background:#fef3c7}} .tag.sent{{background:#dbeafe}} .tag.received{{background:#dcfce7}} .tag.cancelled{{background:#fee2e2}}
.legend{{color:#6b7280;font-size:12px;margin-top:6px}}
</style></head><body><main>
<h1>{escape(title)}</h1>
<div class="sub">Généré le {datetime.now():%d/%m/%Y à %H:%M}</div>
<div class="cards">{cards_html}</div>
<section><h2>État du stock</h2>
<table><tr><th>Réf.</th><th>Produit</th><th class="num">Prix</th><th class="num">Qté</th><th class="num">Seuil</th><th>Niveau</th><th>Fournisseur</th></tr>{product_rows}</table>
<div class="legend">Barre rouge : stock sous le seuil d'alerte. Le trait noir marque le seuil.</div></section>
<section><h2>Réapprovisionnements suggérés</h2>
<table><tr><th>Réf.</th><th>Produit</th><th class="num">Stock</th><th class="num">À commander</th><th>Fournisseur</th></tr>{sug_rows}</table>
<div class="legend">Quantité suggérée = 2 × seuil d'alerte − stock actuel.</div></section>
<section><h2>Commandes fournisseurs</h2>
<table><tr><th>N°</th><th>Fournisseur</th><th>Statut</th><th class="num">Montant</th><th>Créée le</th></tr>{order_rows}</table></section>
<section><h2>Derniers mouvements de stock</h2>
<table><tr><th>Date</th><th>Réf.</th><th class="num">Variation</th><th>Motif</th></tr>{move_rows}</table></section>
</main></body></html>"""
