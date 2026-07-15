"""Maps v1 `contracts` to core_contracts.

contract_type: v1's three values (saas/support/vendor) don't line up
1:1 with v2's (license/contract/subscription) -- v1 has no software-
license concept at all, so nothing ever maps to v2's "license" (an
admin adds those by hand later). saas -> subscription (a recurring
SaaS bill IS a subscription); support and vendor both collapse to
v2's generic "contract" -- vendor -> contract was the explicitly
confirmed mapping in the Phase 9 design, and support fits the same
generic bucket for the same reason (neither is a per-seat license or
a subscription).

status: v2 doesn't store a status column at all -- active/expiring-
soon/expired are COMPUTED at render time from end_date (see
contracts.py's own _renewal_state, contracts.renewal_alert_days
setting), which is more accurate than trusting v1's possibly-stale
stored value. The one v1 status this import can't silently absorb is
"cancelled": nothing about a date makes a contract read as cancelled,
so importing one naively would have it start showing up as
active/expiring/expired in the renewal-tracking list it no longer
belongs in. Cancelled v1 contracts are flagged for manual review
instead of created.

renewal_date is NULLABLE in v1 but v2's end_date is REQUIRED (CLAUDE.md:
"a contract you can't track toward renewal isn't useful here") -- a v1
contract with no renewal_date is flagged, the same "can't safely
satisfy a NOT NULL, don't crash the batch" rule used everywhere else
cost/date fields hit a required v2 column.

billing_cycle has no matching v2 column -- translated into v2's actual
renewal_period_months + auto_renews pair.

vendor_contact_name/email/phone and owner_id have no matching v2
columns either (Contract carries no contact-person or owner fields).
Contact details are folded into `notes` (visible to anyone reading the
contract itself, not just the import log -- more useful for a "who do
I call" field than a Users-location-style detail-only note). owner_id
maps to created_by via the Users mapper's trail, falling back to the
importing admin when the v1 owner hasn't been imported.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.common import record_row, v2_entity_id_for_v1_row
from app.core.models import Contract, ContractType, ImportRowOutcome, V1ImportBatch
from app.core.settings_store import SettingsStore
from app.core.v1_currency import load_symbol_map, parse_v1_money

CONTRACT_TYPE_PLAN = {
    "saas": ContractType.subscription,
    "support": ContractType.contract,
    "vendor": ContractType.contract,
}

BILLING_CYCLE_PLAN = {
    "monthly": (1, True),
    "quarterly": (3, True),
    "annual": (12, True),
    "one_time": (None, False),
}


async def import_contracts(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    symbol_map = load_symbol_map(store.get("import.currency_symbol_map"))

    rows = await source.fetch(
        "SELECT id, name, contract_type, status, vendor_name, vendor_contact_name, vendor_contact_email, "
        "vendor_contact_phone, cost, billing_cycle, start_date, renewal_date, owner_id, notes "
        "FROM contracts ORDER BY id"
    )
    for row in rows:
        v1_status = (row["status"] or "").strip().lower()
        if v1_status == "cancelled":
            await record_row(
                db, batch, "contracts", row["id"], "contract", None, ImportRowOutcome.flagged,
                "v1 status=cancelled -- v2 has no cancelled state; create manually if still relevant",
            )
            continue
        if row["renewal_date"] is None:
            await record_row(
                db, batch, "contracts", row["id"], "contract", None, ImportRowOutcome.flagged,
                "blank renewal_date -- core_contracts.end_date is required",
            )
            continue

        v1_type = (row["contract_type"] or "").strip().lower()
        contract_type = CONTRACT_TYPE_PLAN.get(v1_type, ContractType.contract)

        v1_cycle = (row["billing_cycle"] or "").strip().lower()
        renewal_period_months, auto_renews = BILLING_CYCLE_PLAN.get(v1_cycle, (None, False))

        money = parse_v1_money(row["cost"], symbol_map)
        cost = money.amount if not money.needs_review else None
        currency = money.currency if not money.needs_review else None

        contact_lines = []
        if row["vendor_contact_name"] or row["vendor_contact_email"] or row["vendor_contact_phone"]:
            parts = [p for p in [row["vendor_contact_name"], row["vendor_contact_email"], row["vendor_contact_phone"]] if p]
            contact_lines.append("Vendor contact: " + ", ".join(parts))
        notes_parts = [p for p in [row["notes"]] + contact_lines if p]
        notes = "\n\n".join(notes_parts) or None

        created_by = batch.started_by
        if row["owner_id"]:
            resolved = await v2_entity_id_for_v1_row(db, "users", row["owner_id"])
            if resolved is not None:
                created_by = resolved

        detail_notes = []
        if money.needs_review and (row["cost"] or "").strip():
            detail_notes.append(f"NEEDS REVIEW (cost): raw='{row['cost']}'")

        if dry_run:
            detail = f"would create contract '{row['name']}'"
            if detail_notes:
                detail += "; " + "; ".join(detail_notes)
            await record_row(db, batch, "contracts", row["id"], "contract", None, ImportRowOutcome.created, detail)
            continue

        contract = Contract(
            name=row["name"] or f"v1 contract {row['id']}",
            contract_type=contract_type,
            vendor=row["vendor_name"] or None,
            start_date=row["start_date"],
            end_date=row["renewal_date"],
            cost=cost,
            currency=currency,
            renewal_period_months=renewal_period_months,
            auto_renews=auto_renews,
            notes=notes,
            created_by=created_by,
        )
        db.add(contract)
        await db.flush()

        detail = f"created contract '{contract.name}'"
        if detail_notes:
            detail += "; " + "; ".join(detail_notes)
        await record_row(db, batch, "contracts", row["id"], "contract", contract.id, ImportRowOutcome.created, detail)
