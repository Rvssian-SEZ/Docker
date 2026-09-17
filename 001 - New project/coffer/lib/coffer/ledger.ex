defmodule Coffer.Ledger do
  @moduledoc """
  Ledger transactions. No approval workflow — any Staff/Admin posts directly.
  Edits/deletes are allowed directly (no immutability/reversal-entry
  requirement, spec §4.4) but every write is audit-logged with a full
  before/after snapshot.
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Currencies
  alias Coffer.Accounts.User
  alias Coffer.Ledger.Transaction

  @preloads [:currency, :created_by, :budget_envelope, :contract, :vendor]

  def list_transactions do
    Transaction
    |> order_by(desc: :date, desc: :inserted_at)
    |> preload(^@preloads)
    |> Repo.all()
  end

  def get_transaction!(id), do: Repo.get!(Transaction, id) |> Repo.preload(@preloads)

  @doc """
  `actor` is `nil` only for the system-triggered path (`ContractRenewalWorker`
  auto-posting a due renewal) — every user-facing call site passes a real
  `%User{}`, matching `Coffer.AuditLog`'s documented "no authenticated actor"
  case.
  """
  def create_transaction(attrs, actor) do
    actor_id = actor && actor.id

    changeset =
      %Transaction{}
      |> Transaction.changeset(attrs)
      |> Ecto.Changeset.put_change(:created_by_id, actor_id)
      |> put_amount_base()

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:transaction, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{transaction: t} ->
      AuditLog.record(actor_id, :create, "LedgerTransaction", t.id, %{after: serialize(t)})
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  def update_transaction(%Transaction{} = transaction, attrs, %User{} = actor) do
    before = serialize(transaction)

    changeset =
      transaction
      |> Transaction.changeset(attrs)
      |> put_amount_base()

    Ecto.Multi.new()
    |> Ecto.Multi.update(:transaction, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{transaction: t} ->
      AuditLog.record(actor.id, :update, "LedgerTransaction", t.id, %{
        before: before,
        after: serialize(t)
      })
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  def delete_transaction(%Transaction{} = transaction, %User{} = actor) do
    before = serialize(transaction)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:transaction, transaction)
    |> Ecto.Multi.run(:audit, fn _repo, %{transaction: t} ->
      AuditLog.record(actor.id, :delete, "LedgerTransaction", t.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  def change_transaction(%Transaction{} = transaction, attrs \\ %{}),
    do: Transaction.changeset(transaction, attrs)

  # Computes and stores `amount_base` from the date-effective exchange rate
  # for the (possibly just-changed) date/currency — never recomputed live at
  # read time, so historical reports stay stable even if rates are later
  # corrected (spec §4.4).
  defp put_amount_base(changeset) do
    amount = Ecto.Changeset.get_field(changeset, :amount)
    date = Ecto.Changeset.get_field(changeset, :date)
    currency_id = Ecto.Changeset.get_field(changeset, :currency_id)

    cond do
      is_nil(amount) or is_nil(date) or is_nil(currency_id) ->
        changeset

      currency_id == Currencies.get_base_currency!().id ->
        Ecto.Changeset.put_change(changeset, :amount_base, amount)

      true ->
        case Currencies.rate_for_date(currency_id, date) do
          nil ->
            Ecto.Changeset.add_error(
              changeset,
              :currency_id,
              "no exchange rate on file effective #{date}"
            )

          rate ->
            Ecto.Changeset.put_change(
              changeset,
              :amount_base,
              Decimal.mult(amount, rate.rate_to_base)
            )
        end
    end
  end

  defp serialize(%Transaction{} = t) do
    %{
      id: t.id,
      date: t.date,
      description: t.description,
      amount: Decimal.to_string(t.amount),
      currency_id: t.currency_id,
      amount_base: Decimal.to_string(t.amount_base),
      direction: t.direction,
      quantity: t.quantity,
      budget_envelope_id: t.budget_envelope_id,
      contract_id: t.contract_id,
      vendor_id: t.vendor_id,
      notes: t.notes
    }
  end

  defp unwrap({:ok, %{transaction: result}}), do: {:ok, result}
  defp unwrap({:error, :transaction, changeset, _changes}), do: {:error, changeset}
end
