defmodule Coffer.Exports do
  @moduledoc """
  CSV/XLSX generation for every module's list view (spec §9). Each `*_csv/1`
  function takes the already-loaded (and, where applicable, already-filtered)
  list and returns a binary — `CofferWeb.ExportController` owns fetching the
  data and authorization, this module only owns formatting.

  The ledger CSV is the one exception: `stream_ledger_csv/2` streams rows
  straight from the DB via `Coffer.Repo.stream/2` instead of taking a
  pre-loaded list, since it's the highest-volume table (spec §9's explicit
  callout) and building the whole thing as one binary would hold the full
  result set in memory.
  """

  alias NimbleCSV.RFC4180, as: CSV
  alias Coffer.Repo
  alias Coffer.Ledger.Transaction

  import Ecto.Query, warn: false

  # --- Ledger (streaming) --------------------------------------------

  @ledger_headers ~w(date description direction amount currency amount_base_scr quantity envelope contract vendor posted_by notes)

  @doc """
  Streams the ledger CSV directly to `conn` in chunks, never materializing
  the full result set or the full CSV in memory. `filters` is a
  `Coffer.Reporting` filters map (same shape used by the dashboard and its
  export), or `nil` for the unfiltered `LedgerLive` export.
  """
  def stream_ledger_csv(conn, filters) do
    conn =
      conn
      |> Plug.Conn.put_resp_content_type("text/csv")
      |> Plug.Conn.put_resp_header(
        "content-disposition",
        ~s(attachment; filename="ledger.csv")
      )
      |> Plug.Conn.send_chunked(200)

    {:ok, conn} =
      Repo.transaction(fn ->
        header_iodata = CSV.dump_to_iodata([@ledger_headers])
        {:ok, conn} = Plug.Conn.chunk(conn, header_iodata)

        ledger_query(filters)
        |> Repo.stream(max_rows: 500)
        # `Repo.stream/2` can't use the normal assoc-based `preload` (it
        # issues separate queries per association, which a live cursor
        # can't interleave with) — preload each batch explicitly instead,
        # still bounded (500 rows) rather than the whole table at once.
        |> Stream.chunk_every(500)
        |> Stream.map(
          &Repo.preload(&1, [:currency, :created_by, :budget_envelope, :contract, :vendor])
        )
        |> Enum.reduce(conn, fn transactions, conn ->
          rows = Enum.map(transactions, &ledger_row/1)
          {:ok, conn} = Plug.Conn.chunk(conn, CSV.dump_to_iodata(rows))
          conn
        end)
      end)

    conn
  end

  defp ledger_query(nil) do
    from(t in Transaction, order_by: [desc: t.date, desc: t.inserted_at])
  end

  defp ledger_query(filters), do: Coffer.Reporting.filtered_transactions_query(filters)

  # `ledger_row/1` feeds both the CSV (NimbleCSV, tolerant of any term) and
  # the XLSX export (Elixlsx, which only accepts numbers/strings/booleans —
  # a raw atom like `t.direction` crashes it) — so every field here must
  # already be one of those three types, not just "whatever prints fine."
  defp ledger_row(t) do
    [
      Date.to_iso8601(t.date),
      t.description,
      to_string(t.direction),
      Decimal.to_string(t.amount),
      t.currency.code,
      Decimal.to_string(t.amount_base),
      t.quantity,
      t.budget_envelope && t.budget_envelope.name,
      t.contract && t.contract.name,
      t.vendor && t.vendor.name,
      t.created_by && t.created_by.name,
      t.notes
    ]
  end

  @doc "Full ledger XLSX (spec §9 — formatting helps here, unlike a plain CSV) for an already-loaded, already-filtered transaction list."
  def ledger_xlsx(transactions) do
    rows = [@ledger_headers | Enum.map(transactions, &ledger_row/1)]
    build_xlsx("Ledger", rows)
  end

  # --- Contracts -------------------------------------------------------

  def contracts_csv(contracts) do
    rows = [
      ~w(name vendor type status start_date end_date renewal_date renewal_frequency amount currency auto_post_to_ledger envelope notes)
      | Enum.map(contracts, fn c ->
          [
            c.name,
            c.vendor && c.vendor.name,
            c.contract_type,
            c.status,
            c.start_date && Date.to_iso8601(c.start_date),
            c.end_date && Date.to_iso8601(c.end_date),
            c.renewal_date && Date.to_iso8601(c.renewal_date),
            c.renewal_frequency,
            Decimal.to_string(c.amount),
            c.currency.code,
            c.auto_post_to_ledger,
            c.budget_envelope && c.budget_envelope.name,
            c.notes
          ]
        end)
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Vendors -----------------------------------------------------------

  def vendors_csv(vendors) do
    rows = [
      ~w(name email phone notes)
      | Enum.map(vendors, fn v ->
          contact = v.contact_info || %{}
          [v.name, Map.get(contact, "email"), Map.get(contact, "phone"), v.notes]
        end)
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Budget envelopes ----------------------------------------------

  def envelopes_csv(envelopes) do
    rows = [
      ~w(name category fiscal_year allocated_amount_scr spent_scr remaining_scr active)
      | Enum.map(envelopes, fn e ->
          spent = Decimal.sub(e.allocated_amount, Coffer.Budgets.envelope_remaining(e))

          [
            e.name,
            e.category && e.category.name,
            e.fiscal_year,
            Decimal.to_string(e.allocated_amount),
            Decimal.to_string(spent),
            Decimal.to_string(Coffer.Budgets.envelope_remaining(e)),
            e.active
          ]
        end)
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Currencies ------------------------------------------------------

  def currencies_csv(currencies) do
    rows = [
      ~w(code name symbol is_base)
      | Enum.map(currencies, &[&1.code, &1.name, &1.symbol, &1.is_base])
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Inventory items --------------------------------------------------

  def inventory_items_csv(items) do
    rows = [
      ~w(name tracking_type category quantity_on_hand available reorder_threshold unit_cost location active)
      | Enum.map(items, fn i ->
          available = if i.tracking_type == :checkoutable, do: Coffer.Inventory.available(i)

          [
            i.name,
            i.tracking_type,
            i.category,
            i.quantity_on_hand,
            available,
            i.reorder_threshold,
            i.unit_cost && Decimal.to_string(i.unit_cost),
            i.location,
            i.active
          ]
        end)
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Checkouts -------------------------------------------------------

  def checkouts_csv(checkouts) do
    rows = [
      ~w(item checked_out_to checked_out_by checked_out_at due_back_at checked_in_at status condition_notes_out condition_notes_in)
      | Enum.map(checkouts, fn c ->
          [
            c.inventory_item.name,
            c.checked_out_to,
            c.checked_out_by && c.checked_out_by.name,
            c.checked_out_at && DateTime.to_iso8601(c.checked_out_at),
            c.due_back_at && DateTime.to_iso8601(c.due_back_at),
            c.checked_in_at && DateTime.to_iso8601(c.checked_in_at),
            c.status,
            c.condition_notes_out,
            c.condition_notes_in
          ]
        end)
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Audit log ---------------------------------------------------------

  def audit_log_csv(entries) do
    rows = [
      ~w(timestamp user action resource_type resource_id before after)
      | Enum.map(entries, fn e ->
          [
            DateTime.to_iso8601(e.inserted_at),
            e.user && e.user.name,
            e.action,
            e.resource_type,
            e.resource_id,
            e.before && Jason.encode!(e.before),
            e.after && Jason.encode!(e.after)
          ]
        end)
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Role mappings ---------------------------------------------------

  def role_mappings_csv(role_mappings) do
    rows = [
      ~w(authentik_group app_role)
      | Enum.map(role_mappings, &[&1.authentik_group, &1.app_role])
    ]

    CSV.dump_to_iodata(rows) |> IO.iodata_to_binary()
  end

  # --- Dashboard summary -------------------------------------------------

  @doc "Multi-sheet XLSX mirroring the dashboard's current filtered view (spec §9's 'anything tabular where formatting helps')."
  def dashboard_xlsx(filters) do
    transactions = Coffer.Reporting.filtered_transactions(filters)
    by_envelope = Coffer.Reporting.spend_by_envelope(filters)
    by_category = Coffer.Reporting.spend_by_category(filters)

    transaction_rows = [@ledger_headers | Enum.map(transactions, &ledger_row/1)]

    envelope_rows = [
      ["envelope", "allocated_scr", "spent_scr"]
      | Enum.map(
          by_envelope,
          &[&1.envelope.name, Decimal.to_string(&1.allocated), Decimal.to_string(&1.spent)]
        )
    ]

    category_rows = [
      ["category", "total_scr"]
      | Enum.map(by_category, &[&1.category, Decimal.to_string(&1.total)])
    ]

    %Elixlsx.Workbook{
      sheets: [
        %Elixlsx.Sheet{name: "Transactions", rows: transaction_rows},
        %Elixlsx.Sheet{name: "By envelope", rows: envelope_rows},
        %Elixlsx.Sheet{name: "By category", rows: category_rows}
      ]
    }
    |> Elixlsx.write_to_memory("dashboard.xlsx")
    |> elem(1)
    |> elem(1)
  end

  defp build_xlsx(sheet_name, rows) do
    %Elixlsx.Workbook{sheets: [%Elixlsx.Sheet{name: sheet_name, rows: rows}]}
    |> Elixlsx.write_to_memory("export.xlsx")
    |> elem(1)
    |> elem(1)
  end
end
