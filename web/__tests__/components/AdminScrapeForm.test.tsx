import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

// next/navigation's useRouter requires the App Router runtime; stub it
// so the component renders in jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import { AdminScrapeForm } from "@/components/AdminScrapeForm";

const subjects = [
  { subject_code: "M6-ORL-WPAR", display_name: "Motel 6 Orlando Winter Park" },
  { subject_code: "ESA-AUS-LAKE", display_name: "ESA Austin Lakeline" },
];

describe("<AdminScrapeForm />", () => {
  it("offers Portfolio + each subject in the property dropdown", () => {
    render(<AdminScrapeForm subjects={subjects} />);
    const property = screen.getByLabelText(/Property/i) as HTMLSelectElement;
    const optionLabels = [...property.options].map((o) => o.textContent ?? "");
    expect(optionLabels[0]).toMatch(/Portfolio/);
    expect(optionLabels).toContain("Motel 6 Orlando Winter Park");
    expect(optionLabels).toContain("ESA Austin Lakeline");
  });

  it("offers 1 / 7 / 28 night LOS for booking by default", () => {
    render(<AdminScrapeForm subjects={subjects} />);
    const los = screen.getByLabelText(/Length of stay/i) as HTMLSelectElement;
    const values = [...los.options].map((o) => o.value);
    expect(values).toEqual(["1", "7", "28"]);
  });

  it("hides 28-night option when OTA is brand and shifts the selection down", () => {
    render(<AdminScrapeForm subjects={subjects} />);
    const ota = screen.getByLabelText(/OTA/i) as HTMLSelectElement;
    const los = screen.getByLabelText(/Length of stay/i) as HTMLSelectElement;

    // Pre-flip to 28 nights on booking.
    fireEvent.change(los, { target: { value: "28" } });
    expect(los.value).toBe("28");

    // Switch to brand: 28 must drop and los must auto-shift.
    fireEvent.change(ota, { target: { value: "branddotcom" } });

    const brandValues = [...los.options].map((o) => o.value);
    expect(brandValues).toEqual(["1", "7"]);
    expect(los.value).toBe("7");
    expect(screen.getByText(/Brand\.com has no 28-night data/i)).toBeInTheDocument();
  });
});
