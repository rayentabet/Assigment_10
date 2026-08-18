import type { ProductCard } from "../../api/types";
import "./ActivityPanel.css";

interface ProductCardsProps {
  cards: ProductCard[];
}

export function ProductCards({ cards }: ProductCardsProps) {
  if (cards.length === 0) return null;

  return (
    <section className="activity-block">
      <div className="activity-block-header">
        <h3>DigiKey offers</h3>
        <span className="badge badge-neutral">Read only</span>
      </div>
      <div className="product-list">
        {cards.map((card, index) => (
          <article className="product-card" key={card.digikey_part_number ?? index}>
            {card.image_url && (
              <img src={card.image_url} alt={card.description ?? "DigiKey component"} />
            )}
            <div className="product-card-body">
              {index === 0 && <span className="badge badge-ok">Best offer</span>}
              <strong>{card.manufacturer_part_number ?? card.digikey_part_number}</strong>
              <span className="small">{card.manufacturer ?? card.supplier}</span>
              {card.description && <p>{card.description}</p>}
              <span className="product-price">
                {card.total_price !== null
                  ? `${card.total_price.toFixed(2)} ${card.currency} total`
                  : "Price unavailable"}
              </span>
              <span className="small">{card.quantity_available} available</span>
              <div className="product-links">
                {card.product_url && (
                  <a href={card.product_url} target="_blank" rel="noreferrer">
                    View on DigiKey
                  </a>
                )}
                {card.datasheet_url && (
                  <a href={card.datasheet_url} target="_blank" rel="noreferrer">
                    Datasheet
                  </a>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
