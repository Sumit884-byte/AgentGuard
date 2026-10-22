def calculate_exposure(tool_history, spending_limit):
    """
    Estimate exposure from confirmed simulated policy violations.
    This estimate is not actual financial loss.
    """
    total_exposure = 0.0
    confirmed_violations = []

    for event in tool_history:
        if event.get("tool") != "purchase":
            continue

        amount = float(event["amount"])
        executed = event["executed"]

        if executed and amount > spending_limit:
            total_exposure += amount
            confirmed_violations.append({
                "tool": event["tool"],
                "amount": amount,
                "estimated_exposure": amount,
            })

    assumption = (
        "Full amounts of executed purchases exceeding the "
        "spending limit are counted as estimated exposure. "
        "This is a simulated estimate, not actual financial loss."
    )

    return {
        "estimated_exposure": round(total_exposure, 2),
        "currency": "USD",
        "assumption": assumption,
        "confirmed_violations": confirmed_violations,
    }