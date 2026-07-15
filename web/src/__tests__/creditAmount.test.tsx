import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CreditAmount } from "../components/ui/CreditAmount";

describe("CreditAmount", () => {
  it("uses plain language by default for transactional costs", () => {
    render(<CreditAmount value={5} approximate />);

    expect(screen.getByText("~5 credits")).toBeTruthy();
    expect(screen.queryByText("◆")).toBeNull();
  });

  it("lets compact counters replace the label with the credit mark", () => {
    render(<CreditAmount value={1240} showMark showLabel={false} />);

    expect(screen.getByText("◆")).toBeTruthy();
    expect(screen.getByText("1,240")).toBeTruthy();
    expect(screen.getByLabelText("1,240 credits")).toBeTruthy();
  });
});
