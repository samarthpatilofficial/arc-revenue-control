import { describe, expect, it } from "vitest";
import { displayDetail, displayEnum } from "./display";
import { formatMoney } from "./format";

describe("display utilities", () => {
  it("converts INR minor units without displaying raw minor values", () => {
    expect(formatMoney(1_000, "INR")).toBe("₹10.00");
    expect(formatMoney(null, "INR")).toBe("—");
  });

  it("uses centralized human-readable enum labels", () => {
    expect(displayEnum("WAITING_FOR_OUTCOME")).toBe("Waiting for outcome");
    expect(displayEnum("CREATE_RECOVERY_LINK")).toBe("Create recovery link");
    expect(displayEnum("CUSTOMER_AUTHENTICATION")).toBe("Customer Authentication");
    expect(
      displayDetail("CUSTOMER_AUTHENTICATION / CUSTOMER_ACTION_REQUIRED"),
    ).toBe("Customer Authentication / Customer Action Required");
  });
});
