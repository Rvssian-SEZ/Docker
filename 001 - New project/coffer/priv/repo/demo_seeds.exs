# Populates a handful of realistic sample records across every module, for
# demoing/evaluating Coffer on a fresh TEST deployment.
#
# TEST/DEMO USE ONLY — NEVER RUN THIS AGAINST A REAL PRODUCTION DEPLOYMENT
# (it creates a synthetic admin user and sample business data that has no
# place in a real organization's ledger). Deliberately NOT wired into the
# Dockerfile's automatic migrate/seed boot chain — run it explicitly:
#
#     mix run priv/repo/demo_seeds.exs   (dev)
#     bin/demo_seed                      (release, e.g. `docker exec <container> /app/bin/demo_seed`)
#
# Idempotent: safe to run more than once, each record is looked up by a
# natural key first and only created if missing.

import Ecto.Query

alias Coffer.Repo
alias Coffer.Accounts.User
alias Coffer.{Currencies, Budgets, Vendors, Contracts, Ledger, Inventory}

actor =
  case Repo.get_by(User, authentik_sub: "demo-seed-script") do
    %User{} = u ->
      u

    nil ->
      Repo.insert!(%User{
        authentik_sub: "demo-seed-script",
        email: "demo-seed@example.invalid",
        name: "Demo Seed",
        role: :admin,
        active: true
      })
  end

usd =
  case Repo.get_by(Currencies.Currency, code: "USD") do
    %Currencies.Currency{} = c ->
      c

    nil ->
      {:ok, c} =
        Currencies.create_currency(
          %{"code" => "USD", "name" => "US Dollar", "symbol" => "$"},
          actor
        )

      c
  end

if Currencies.rate_for_date(usd.id, ~D[2026-01-01]) == nil do
  {:ok, _} =
    Currencies.create_exchange_rate(
      %{"currency_id" => usd.id, "rate_to_base" => "13.5", "effective_from" => "2026-01-01"},
      actor
    )
end

category =
  case Repo.get_by(Budgets.Category, name: "Operations") do
    %Budgets.Category{} = c ->
      c

    nil ->
      {:ok, c} = Budgets.create_category(%{"name" => "Operations"}, actor)
      c
  end

envelope =
  case Repo.get_by(Budgets.Envelope, name: "Office Supplies", fiscal_year: 2026) do
    %Budgets.Envelope{} = e ->
      e

    nil ->
      {:ok, e} =
        Budgets.create_envelope(
          %{
            "name" => "Office Supplies",
            "description" => "Day-to-day office consumables",
            "fiscal_year" => "2026",
            "allocated_amount" => "20000",
            "category_id" => category.id
          },
          actor
        )

      e
  end

vendor =
  case Repo.get_by(Vendors.Vendor, name: "Acme Supplies Co.") do
    %Vendors.Vendor{} = v ->
      v

    nil ->
      {:ok, v} =
        Vendors.create_vendor(
          %{
            "name" => "Acme Supplies Co.",
            "contact_info" => %{"email" => "sales@acme.example"},
            "notes" => "Demo vendor"
          },
          actor
        )

      v
  end

base = Currencies.get_base_currency!()

contract =
  case Repo.get_by(Contracts.Contract, name: "Office Cleaning Service") do
    %Contracts.Contract{} = c ->
      c

    nil ->
      {:ok, c} =
        Contracts.create_contract(
          %{
            "name" => "Office Cleaning Service",
            "vendor_id" => vendor.id,
            "contract_type" => "subscription",
            "start_date" => "2026-01-01",
            "renewal_date" => "2026-12-01",
            "renewal_frequency" => "monthly",
            "amount" => "1500",
            "currency_id" => base.id,
            "budget_envelope_id" => envelope.id,
            "auto_post_to_ledger" => false,
            "status" => "active",
            "notes" => "Demo contract"
          },
          actor
        )

      c
  end

demo_txns = [
  %{
    "date" => "2026-01-15",
    "description" => "Client payment received",
    "amount" => "5000",
    "currency_id" => base.id,
    "direction" => "income",
    "notes" => "Demo income transaction"
  },
  %{
    "date" => "2026-01-20",
    "description" => "Printer paper and pens",
    "amount" => "450",
    "currency_id" => base.id,
    "direction" => "expense",
    "budget_envelope_id" => envelope.id,
    "vendor_id" => vendor.id,
    "notes" => "Demo expense transaction"
  },
  %{
    "date" => "2026-02-01",
    "description" => "Software license (USD)",
    "amount" => "99",
    "currency_id" => usd.id,
    "direction" => "expense",
    "vendor_id" => vendor.id,
    "notes" => "Demo foreign-currency expense"
  }
]

for attrs <- demo_txns do
  exists? =
    Repo.exists?(from(t in Ledger.Transaction, where: t.description == ^attrs["description"]))

  unless exists? do
    {:ok, _} = Ledger.create_transaction(attrs, actor)
  end
end

consumable =
  case Repo.get_by(Inventory.Item, name: "A4 Paper (ream)") do
    %Inventory.Item{} = i ->
      i

    nil ->
      {:ok, i} =
        Inventory.create_item(
          %{
            "name" => "A4 Paper (ream)",
            "description" => "Standard printer paper",
            "tracking_type" => "consumable",
            "category" => "Office Supplies",
            "quantity_on_hand" => "50",
            "reorder_threshold" => "10",
            "unit_cost" => "3.50",
            "location" => "Supply closet"
          },
          actor
        )

      i
  end

if Repo.all(from(t in Inventory.Transaction, where: t.inventory_item_id == ^consumable.id)) == [] do
  {:ok, _} =
    Inventory.issue_stock(
      consumable,
      %{
        "quantity" => "5",
        "date" => "2026-01-10",
        "issued_to" => "Front desk",
        "notes" => "Demo issue"
      },
      actor
    )
end

checkoutable =
  case Repo.get_by(Inventory.Item, name: "Projector") do
    %Inventory.Item{} = i ->
      i

    nil ->
      {:ok, i} =
        Inventory.create_item(
          %{
            "name" => "Projector",
            "description" => "Portable meeting-room projector",
            "tracking_type" => "checkoutable",
            "category" => "Equipment",
            "quantity_on_hand" => "2",
            "location" => "IT storage"
          },
          actor
        )

      i
  end

if Repo.all(from(c in Inventory.Checkout, where: c.inventory_item_id == ^checkoutable.id)) == [] do
  {:ok, _} =
    Inventory.checkout_item(
      checkoutable,
      %{"checked_out_to" => "Jane Doe", "due_back_at" => "2026-03-01T00:00:00Z"},
      actor
    )
end

IO.puts("Demo data seeded.")
