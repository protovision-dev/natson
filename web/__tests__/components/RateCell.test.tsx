import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RateCell } from "@/components/RateCell";
import type { RateCell as Cell } from "@/lib/queries";

const baseCell: Cell = {
  competitor_hotelinfo_id: "1",
  competitor_name: "Test Hotel",
  is_own: false,
  rate_value: 99,
  shop_value: 693,
  all_in_price: 770,
  is_available: true,
  message: "",
  observation_ts: "2026-04-19T10:00:00Z",
  extract_datetime: "2026-04-19T08:00:00Z",
};

describe("<RateCell />", () => {
  it("renders em-dash when cell is null", () => {
    render(<RateCell cell={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders 'Sold out' when is_available is false", () => {
    render(
      <RateCell
        cell={{ ...baseCell, is_available: false, rate_value: null, message: "rates.soldout" }}
      />,
    );
    expect(screen.getByText("Sold out")).toBeInTheDocument();
  });

  it("renders the rate as $ NN for an available numeric value", () => {
    render(<RateCell cell={baseCell} />);
    expect(screen.getByText("$ 99")).toBeInTheDocument();
  });

  it("renders em-dash when rate_value is null but cell is technically available", () => {
    render(<RateCell cell={{ ...baseCell, rate_value: null }} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
