defmodule Coffer.Reporting do
  @moduledoc """
  Dashboard queries and filter logic (spec §8). Every summary here is
  computed at query time against the live ledger — nothing is cached or
  stored, same principle as `Coffer.Budgets.envelope_remaining/1`.

  All functions take a `filters` map (atom keys):

      %{
        date_from: ~D[...], date_to: ~D[...],
        envelope_ids: [id, ...], category_ids: [id, ...], vendor_ids: [id, ...],
        currency_id: id | nil, direction: :income | :expense | nil
      }

  Empty lists / `nil` mean "no constraint on this field."
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.Ledger.Transaction
  alias Coffer.Budgets

  def default_filters do
    year = Coffer.FiscalYear.current_year()

    %{
      date_from: Coffer.FiscalYear.start_date(year),
      date_to: Coffer.FiscalYear.end_date(year),
      envelope_ids: [],
      category_ids: [],
      vendor_ids: [],
      currency_id: nil,
      direction: nil
    }
  end

  @doc "Every transaction matching `filters`, most recent first — backs the raw list, not just summaries."
  def filtered_transactions(filters) do
    filters
    |> filtered_transactions_query()
    |> preload([:currency, :created_by, :budget_envelope, :contract, :vendor])
    |> Repo.all()
  end

  @doc """
  The un-preloaded query behind `filtered_transactions/1` — exposed for
  `Coffer.Exports.stream_ledger_csv/2`, which streams raw rows via
  `Repo.stream/2` (assoc-based `preload` isn't supported on a streamed
  query) and preloads each chunk manually instead.
  """
  def filtered_transactions_query(filters) do
    filters
    |> filtered_query()
    |> order_by([t], desc: t.date, desc: t.inserted_at)
  end

  @doc "Sum of `amount_base` for expense transactions matching `filters`, in SCR."
  def total_expenditure(filters) do
    filters
    |> filtered_query()
    |> where([t], t.direction == :expense)
    |> select([t], sum(t.amount_base))
    |> Repo.one()
    |> zero_if_nil()
  end

  @doc """
  When `filters.currency_id` is set, the raw (unconverted) `amount` subtotal
  for expense transactions in that one currency — summing raw amounts across
  DIFFERENT currencies would be meaningless, so this is only ever a
  single-currency figure, `nil` when no currency filter is active.
  """
  def currency_subtotal(%{currency_id: nil}), do: nil

  def currency_subtotal(filters) do
    filters
    |> filtered_query()
    |> where([t], t.direction == :expense)
    |> select([t], sum(t.amount))
    |> Repo.one()
    |> zero_if_nil()
  end

  @doc """
  Spend vs `allocated_amount` for each relevant envelope. If
  `filters.envelope_ids` is set, uses exactly those; otherwise defaults to
  every active envelope whose `fiscal_year` overlaps the selected date
  range (further narrowed by `filters.category_ids` if set).
  """
  def spend_by_envelope(filters) do
    spent_by_envelope_id =
      filters
      |> filtered_query()
      |> where([t], t.direction == :expense and not is_nil(t.budget_envelope_id))
      |> group_by([t], t.budget_envelope_id)
      |> select([t], {t.budget_envelope_id, sum(t.amount_base)})
      |> Repo.all()
      |> Map.new()

    filters
    |> relevant_envelopes()
    |> Enum.map(fn envelope ->
      %{
        envelope: envelope,
        spent: Map.get(spent_by_envelope_id, envelope.id, Decimal.new(0)),
        allocated: envelope.allocated_amount
      }
    end)
  end

  @doc "Expense `amount_base` grouped by the envelope's category (unenveloped/uncategorized spend grouped under \"Uncategorized\")."
  def spend_by_category(filters) do
    categories_by_id = Map.new(Budgets.list_categories(), &{&1.id, &1.name})

    filters
    |> filtered_query()
    |> where([t], t.direction == :expense)
    |> group_by([envelope: e], e.category_id)
    |> select([t, envelope: e], {e.category_id, sum(t.amount_base)})
    |> Repo.all()
    |> Enum.map(fn {category_id, total} ->
      %{category: Map.get(categories_by_id, category_id, "Uncategorized"), total: total}
    end)
    |> Enum.sort_by(& &1.total, {:desc, Decimal})
  end

  @doc "Expense `amount_base` bucketed by calendar month within the filtered range, chronological."
  def spend_over_time(filters) do
    # Cast to `::date` (rather than leaving Postgres's `date_trunc` result as
    # a timestamp) so Postgrex decodes each bucket straight into an Elixir
    # `Date`, matching the `{Date.t(), Decimal.t()}` points `CofferWeb.Charts.line_chart/1` expects.
    filters
    |> filtered_query()
    |> where([t], t.direction == :expense)
    |> group_by([t], fragment("date_trunc('month', ?)::date", t.date))
    |> select([t], {fragment("date_trunc('month', ?)::date", t.date), sum(t.amount_base)})
    |> order_by([t], fragment("date_trunc('month', ?)::date", t.date))
    |> Repo.all()
  end

  defp filtered_query(filters) do
    from(t in Transaction,
      left_join: e in assoc(t, :budget_envelope),
      as: :envelope,
      where: t.date >= ^filters.date_from and t.date <= ^filters.date_to
    )
    |> filter_in(filters.envelope_ids, :budget_envelope_id)
    |> filter_category(filters.category_ids)
    |> filter_in(filters.vendor_ids, :vendor_id)
    |> filter_eq(filters.currency_id, :currency_id)
    |> filter_eq(filters.direction, :direction)
  end

  defp filter_in(query, [], _field), do: query

  defp filter_in(query, ids, :budget_envelope_id),
    do: where(query, [t], t.budget_envelope_id in ^ids)

  defp filter_in(query, ids, :vendor_id), do: where(query, [t], t.vendor_id in ^ids)

  defp filter_category(query, []), do: query
  defp filter_category(query, ids), do: where(query, [envelope: e], e.category_id in ^ids)

  defp filter_eq(query, nil, _field), do: query
  defp filter_eq(query, value, :currency_id), do: where(query, [t], t.currency_id == ^value)
  defp filter_eq(query, value, :direction), do: where(query, [t], t.direction == ^value)

  defp relevant_envelopes(%{envelope_ids: [_ | _] = ids}) do
    ids
    |> Enum.map(&Budgets.get_envelope!/1)
    |> maybe_filter_by_category(nil)
  end

  defp relevant_envelopes(%{date_from: from, date_to: to, category_ids: category_ids}) do
    years = from.year..to.year

    Budgets.list_envelopes()
    |> Enum.filter(&(&1.active and &1.fiscal_year in years))
    |> maybe_filter_by_category(category_ids)
  end

  defp maybe_filter_by_category(envelopes, nil), do: envelopes
  defp maybe_filter_by_category(envelopes, []), do: envelopes

  defp maybe_filter_by_category(envelopes, category_ids),
    do: Enum.filter(envelopes, &(&1.category_id in category_ids))

  defp zero_if_nil(nil), do: Decimal.new(0)
  defp zero_if_nil(%Decimal{} = value), do: value

  @doc """
  Builds a `filters` map from raw string-keyed params — shared by
  `DashboardLive`'s `phx-change` handler and `CofferWeb.ExportController`, so
  a dashboard export always matches exactly what's on screen (spec §9: never
  silently export more than the applied filters).
  """
  def parse_filters(params) do
    defaults = default_filters()

    %{
      date_from: parse_date(params["date_from"]) || defaults.date_from,
      date_to: parse_date(params["date_to"]) || defaults.date_to,
      envelope_ids: Map.get(params, "envelope_ids", []),
      category_ids: Map.get(params, "category_ids", []),
      vendor_ids: Map.get(params, "vendor_ids", []),
      currency_id: blank_to_nil(params["currency_id"]),
      direction: parse_direction(params["direction"])
    }
  end

  @doc "Inverse of `parse_filters/1` — turns a filters map into query params for an export link's `href`."
  def to_query_params(filters) do
    %{
      "date_from" => filters.date_from && Date.to_iso8601(filters.date_from),
      "date_to" => filters.date_to && Date.to_iso8601(filters.date_to),
      "envelope_ids" => filters.envelope_ids,
      "category_ids" => filters.category_ids,
      "vendor_ids" => filters.vendor_ids,
      "currency_id" => filters.currency_id,
      "direction" => filters.direction && Atom.to_string(filters.direction)
    }
    |> Enum.reject(fn {_k, v} -> is_nil(v) end)
  end

  defp parse_date(nil), do: nil
  defp parse_date(""), do: nil

  defp parse_date(str) do
    case Date.from_iso8601(str) do
      {:ok, date} -> date
      _ -> nil
    end
  end

  defp blank_to_nil(nil), do: nil
  defp blank_to_nil(""), do: nil
  defp blank_to_nil(value), do: value

  defp parse_direction(nil), do: nil
  defp parse_direction(""), do: nil
  defp parse_direction("income"), do: :income
  defp parse_direction("expense"), do: :expense
  defp parse_direction(_other), do: nil
end
