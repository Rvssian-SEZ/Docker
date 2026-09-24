defmodule Coffer.Currencies do
  @moduledoc """
  Currencies and their date-effective exchange rates. Rate lookups for any
  transaction must use `effective_from`/`effective_to` range matching against
  the transaction date — never "current rate" — so historical reports stay
  stable (spec §4.2).
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Accounts.User
  alias Coffer.Currencies.{Currency, ExchangeRate}

  def list_currencies, do: Repo.all(from c in Currency, order_by: c.code)
  def get_currency!(id), do: Repo.get!(Currency, id)
  def get_base_currency!, do: Repo.get_by!(Currency, is_base: true)

  def create_currency(attrs, %User{} = actor) do
    changeset = Currency.changeset(%Currency{}, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:currency, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{currency: c} ->
      AuditLog.record(actor.id, :create, "Currency", c.id, %{after: serialize_currency(c)})
    end)
    |> Repo.transaction()
    |> unwrap(:currency)
  end

  def update_currency(%Currency{} = currency, attrs, %User{} = actor) do
    before = serialize_currency(currency)
    changeset = Currency.changeset(currency, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:currency, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{currency: c} ->
      AuditLog.record(actor.id, :update, "Currency", c.id, %{
        before: before,
        after: serialize_currency(c)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:currency)
  end

  def change_currency(%Currency{} = currency, attrs \\ %{}),
    do: Currency.changeset(currency, attrs)

  def change_exchange_rate(%ExchangeRate{} = exchange_rate, attrs \\ %{}),
    do: ExchangeRate.changeset(exchange_rate, attrs)

  def list_exchange_rates(currency_id) do
    ExchangeRate
    |> where(currency_id: ^currency_id)
    |> order_by(desc: :effective_from)
    |> Repo.all()
  end

  def get_exchange_rate!(id), do: Repo.get!(ExchangeRate, id)

  @doc """
  Directly edits or removes an already-committed rate row. Unlike
  `create_exchange_rate/2`, this does NOT touch any other row's
  `effective_to` — it's a correction to the row itself (e.g. fixing a typo'd
  rate or date), not a new rate period, so the auto-close behavior in
  `create_exchange_rate/2` doesn't apply here.
  """
  def update_exchange_rate(%ExchangeRate{} = rate, attrs, %User{} = actor) do
    before = serialize_rate(rate)
    changeset = ExchangeRate.changeset(rate, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:exchange_rate, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{exchange_rate: r} ->
      AuditLog.record(actor.id, :update, "ExchangeRate", r.id, %{
        before: before,
        after: serialize_rate(r)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:exchange_rate)
  end

  def delete_exchange_rate(%ExchangeRate{} = rate, %User{} = actor) do
    before = serialize_rate(rate)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:exchange_rate, rate)
    |> Ecto.Multi.run(:audit, fn _repo, %{exchange_rate: r} ->
      AuditLog.record(actor.id, :delete, "ExchangeRate", r.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap(:exchange_rate)
  end

  @doc """
  Finds the exchange rate in effect for `currency_id` on `date`, matching
  `effective_from <= date <= effective_to` (or an open-ended row with
  `effective_to == nil`). Returns `nil` if no rate has been entered yet for
  that date.
  """
  def rate_for_date(currency_id, %Date{} = date) do
    ExchangeRate
    |> where([r], r.currency_id == ^currency_id)
    |> where([r], r.effective_from <= ^date)
    |> where([r], is_nil(r.effective_to) or r.effective_to >= ^date)
    |> Repo.one()
  end

  @doc """
  Creates a new exchange rate row. If an open-ended row (`effective_to`
  nil) already exists for this currency, it is auto-closed to the day
  before the new row's `effective_from` (spec §4.2) in the same
  transaction.
  """
  def create_exchange_rate(attrs, %User{} = actor) do
    changeset = ExchangeRate.changeset(%ExchangeRate{}, Map.put(attrs, "created_by_id", actor.id))

    Ecto.Multi.new()
    |> Ecto.Multi.run(:close_previous, fn repo, _changes ->
      close_previous_open_ended_rate(repo, changeset, actor)
    end)
    |> Ecto.Multi.insert(:exchange_rate, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{exchange_rate: rate} ->
      AuditLog.record(actor.id, :create, "ExchangeRate", rate.id, %{
        after: serialize_rate(rate)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:exchange_rate)
  end

  defp close_previous_open_ended_rate(repo, changeset, actor) do
    with currency_id when not is_nil(currency_id) <-
           Ecto.Changeset.get_field(changeset, :currency_id),
         effective_from when not is_nil(effective_from) <-
           Ecto.Changeset.get_field(changeset, :effective_from),
         %ExchangeRate{} = previous <-
           repo.one(
             from r in ExchangeRate,
               where: r.currency_id == ^currency_id and is_nil(r.effective_to)
           ) do
      before = serialize_rate(previous)
      new_effective_to = Date.add(effective_from, -1)

      previous
      |> ExchangeRate.changeset(%{effective_to: new_effective_to})
      |> repo.update()
      |> case do
        {:ok, updated} ->
          AuditLog.record(actor.id, :update, "ExchangeRate", updated.id, %{
            before: before,
            after: serialize_rate(updated)
          })

          {:ok, updated}

        error ->
          error
      end
    else
      nil -> {:ok, nil}
      _ -> {:ok, nil}
    end
  end

  defp serialize_currency(%Currency{} = c) do
    %{id: c.id, code: c.code, name: c.name, symbol: c.symbol, is_base: c.is_base}
  end

  defp serialize_rate(%ExchangeRate{} = r) do
    %{
      id: r.id,
      currency_id: r.currency_id,
      rate_to_base: Decimal.to_string(r.rate_to_base),
      effective_from: r.effective_from,
      effective_to: r.effective_to
    }
  end

  defp unwrap({:ok, %{exchange_rate: result}}, :exchange_rate), do: {:ok, result}
  defp unwrap({:ok, %{currency: result}}, :currency), do: {:ok, result}

  defp unwrap({:error, _failed_op, changeset, _changes}, _key), do: {:error, changeset}
end
