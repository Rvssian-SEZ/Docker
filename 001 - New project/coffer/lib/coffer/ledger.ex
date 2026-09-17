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

  @preloads [:currency, :created_by, :budget_envelope, :contract, :vendor, :recurrence_source]

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
      |> put_next_occurrence_date()

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
      |> put_next_occurrence_date()

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

  @doc """
  Creates one auto-generated occurrence of a recurring transaction, copying
  the root's fields and linking back via `recurrence_source_id` — the copy
  is NOT itself recurring (`recurrence_frequency` stays nil on it; only the
  root ever carries a frequency / advances `next_occurrence_date`), matching
  how `ContractRenewalWorker`-generated transactions link back via
  `contract_id` instead. Used only by `RecurringTransactionWorker`.
  """
  def create_recurring_instance(%Transaction{} = root, %Date{} = date) do
    attrs = %{
      "date" => date,
      "description" => root.description,
      "amount" => root.amount,
      "currency_id" => root.currency_id,
      "direction" => root.direction,
      "quantity" => root.quantity,
      "budget_envelope_id" => root.budget_envelope_id,
      "vendor_id" => root.vendor_id,
      "notes" => root.notes
    }

    changeset =
      %Transaction{}
      |> Transaction.changeset(attrs)
      |> Ecto.Changeset.put_change(:recurrence_source_id, root.id)
      |> put_amount_base()

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:transaction, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{transaction: t} ->
      AuditLog.record(nil, :create, "LedgerTransaction", t.id, %{after: serialize(t)})
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  @doc """
  System-triggered update (advancing `next_occurrence_date` on a recurring
  root) — used only by `RecurringTransactionWorker`, which has no
  authenticated actor. `actor_id` is nil in the audit entry, matching the
  documented "no authenticated actor" case in `Coffer.AuditLog`.
  """
  def system_update_transaction(%Transaction{} = transaction, attrs) do
    before = serialize(transaction)
    changeset = Transaction.system_changeset(transaction, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:transaction, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{transaction: t} ->
      AuditLog.record(nil, :update, "LedgerTransaction", t.id, %{
        before: before,
        after: serialize(t)
      })
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  @doc "Root recurring transactions due to spawn their next occurrence."
  def list_due_recurring(today \\ Date.utc_today()) do
    Transaction
    |> where([t], not is_nil(t.recurrence_frequency))
    |> where([t], t.next_occurrence_date <= ^today)
    |> Repo.all()
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

  # Whenever `recurrence_frequency` is set (on create, or turned on/changed
  # on edit) — or `date` changes while a frequency is already set — (re)seed
  # `next_occurrence_date` one cycle out from `date`. Clearing the frequency
  # clears the date too, since an unset frequency means "not recurring."
  defp put_next_occurrence_date(changeset) do
    frequency = Ecto.Changeset.get_field(changeset, :recurrence_frequency)
    date = Ecto.Changeset.get_field(changeset, :date)

    cond do
      is_nil(frequency) ->
        Ecto.Changeset.put_change(changeset, :next_occurrence_date, nil)

      is_nil(date) ->
        changeset

      Ecto.Changeset.get_change(changeset, :recurrence_frequency) ||
          Ecto.Changeset.get_change(changeset, :date) ->
        next = Coffer.Dates.add_months(date, cycle_months(frequency))
        Ecto.Changeset.put_change(changeset, :next_occurrence_date, next)

      true ->
        changeset
    end
  end

  defp cycle_months(:monthly), do: 1
  defp cycle_months(:quarterly), do: 3
  defp cycle_months(:annually), do: 12

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
      notes: t.notes,
      recurrence_frequency: t.recurrence_frequency,
      next_occurrence_date: t.next_occurrence_date,
      recurrence_source_id: t.recurrence_source_id
    }
  end

  defp unwrap({:ok, %{transaction: result}}), do: {:ok, result}
  defp unwrap({:error, :transaction, changeset, _changes}), do: {:error, changeset}
end
