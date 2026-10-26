def normalize_phone(phone):
    if not phone:
        return phone
    phone = str(phone).strip().replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith("0"):
        return "254" + phone[1:]
    if phone.startswith("7") or phone.startswith("1"):
        return "254" + phone
    if phone.startswith("254"):
        return phone
    return phone
