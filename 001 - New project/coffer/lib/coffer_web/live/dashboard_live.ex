defmodule CofferWeb.DashboardLive do
  use CofferWeb, :live_view

  alias Coffer.Reporting
  alias Coffer.Currencies
  alias Coffer.Budgets
  alias Coffer.Vendors
  alias Coffer.Authorization.Policy
  alias CofferWeb.Charts

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :ledger_transaction) do
      filters = Reporting.default_filters()

      {:ok,
       socket
       |> assign(:page_title, "Dashboard")
       |> assign(:filters, filters)
       |> assign(:currencies, Currencies.list_currencies())
       |> assign(:envelopes, Budgets.list_envelopes())
       |> assign(:categories, Budgets.list_categories())
       |> assign(:vendors, Vendors.list_vendors())
       |> load_report(filters)}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view the dashboard.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_event("filter", params, socket) do
    filters = parse_filters(params)
    {:noreply, socket |> assign(:filters, filters) |> load_report(filters)}
  end

  defp load_report(socket, filters) do
    by_category = Reporting.spend_by_category(filters)
    category_max = Enum.reduce(by_category, Decimal.new(0), &Decimal.max(&1.total, &2))

    socket
    |> assign(:total_expenditure, Reporting.total_expenditure(filters))
    |> assign(:currency_subtotal, Reporting.currency_subtotal(filters))
    |> assign(:by_envelope, Reporting.spend_by_envelope(filters))
    |> assign(:by_category, by_category)
    |> assign(:category_max, category_max)
    |> assign(:over_time, Reporting.spend_over_time(filters))
    |> assign(:transactions, filters |> Reporting.filtered_transactions() |> Enum.take(50))
  end

  defp parse_filters(params), do: Reporting.parse_filters(params)

  defp currency_code(currencies, id),
    do: Enum.find_value(currencies, "", &(&1.id == id && &1.code))

  defp envelope_filter_label(_envelopes, []), do: "All envelopes"

  defp envelope_filter_label(envelopes, [id]) do
    Enum.find_value(envelopes, "1 selected", &(&1.id == id && &1.name))
  end

  defp envelope_filter_label(_envelopes, ids), do: "#{length(ids)} selected"

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-5xl py-12 space-y-8">
      <.header>
        Dashboard
        <:actions>
          <.link
            href={~p"/dashboard/export.csv?#{Reporting.to_query_params(@filters)}"}
            class="btn btn-outline"
          >
            Export CSV
          </.link>
          <.link
            href={~p"/dashboard/export.xlsx?#{Reporting.to_query_params(@filters)}"}
            class="btn btn-outline"
          >
            Export XLSX
          </.link>
          <.link href={~p"/ledger"} class="link">View full ledger &rarr;</.link>
        </:actions>
      </.header>

      <form
        phx-change="filter"
        class="grid grid-cols-2 gap-4 rounded-box border border-base-300 p-4 sm:grid-cols-3 lg:grid-cols-6"
      >
        <.input type="date" name="date_from" label="From" value={@filters.date_from} />
        <.input type="date" name="date_to" label="To" value={@filters.date_to} />
        <div class="fieldset mb-2">
          <label>
            <span class="label mb-1">Envelope</span>
            <details class="dropdown w-full">
              <summary class="select w-full">
                {envelope_filter_label(@envelopes, @filters.envelope_ids)}
              </summary>
              <ul class="dropdown-content menu z-10 max-h-64 w-full flex-nowrap overflow-y-auto rounded-box bg-base-100 p-2 shadow">
                <li :for={e <- @envelopes}>
                  <label class="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      name="envelope_ids[]"
                      value={e.id}
                      checked={e.id in @filters.envelope_ids}
                      class="checkbox checkbox-sm"
                    />
                    {e.name} (FY{e.fiscal_year})
                  </label>
                </li>
                <li :if={@envelopes == []} class="px-2 py-1 text-sm text-base-content/60">
                  No envelopes yet.
                </li>
              </ul>
            </details>
          </label>
        </div>
        <.input
          type="select"
          name="category_ids[]"
          label="Category"
          multiple
          value={@filters.category_ids}
          options={Enum.map(@categories, &{&1.name, &1.id})}
        />
        <.input
          type="select"
          name="vendor_ids[]"
          label="Vendor"
          multiple
          value={@filters.vendor_ids}
          options={Enum.map(@vendors, &{&1.name, &1.id})}
        />
        <.input
          type="select"
          name="currency_id"
          label="Currency"
          prompt="All (converted to SCR)"
          value={@filters.currency_id}
          options={Enum.map(@currencies, &{&1.code, &1.id})}
        />
        <.input
          type="select"
          name="direction"
          label="Direction"
          prompt="All"
          value={@filters.direction}
          options={[{"Income", "income"}, {"Expense", "expense"}]}
        />
      </form>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div class="rounded-box border border-base-300 p-4">
          <p class="text-sm text-base-content/60">Total expenditure (SCR)</p>
          <p class="text-3xl font-semibold">{@total_expenditure}</p>
        </div>
        <div :if={@currency_subtotal} class="rounded-box border border-base-300 p-4">
          <p class="text-sm text-base-content/60">
            Total expenditure ({currency_code(@currencies, @filters.currency_id)})
          </p>
          <p class="text-3xl font-semibold">{@currency_subtotal}</p>
        </div>
      </div>

      <div class="rounded-box border border-base-300 p-4">
        <h2 class="mb-4 text-lg font-semibold">Spend by envelope</h2>
        <p :if={@by_envelope == []} class="text-sm text-base-content/60">No envelopes in range.</p>
        <div class="space-y-3">
          <Charts.progress_bar
            :for={row <- @by_envelope}
            label={row.envelope.name}
            value={row.spent}
            max={row.allocated}
          />
        </div>
      </div>

      <div class="rounded-box border border-base-300 p-4">
        <h2 class="mb-4 text-lg font-semibold">Spend by category</h2>
        <p :if={@by_category == []} class="text-sm text-base-content/60">No spend in range.</p>
        <div class="space-y-3">
          <Charts.bar_row
            :for={row <- @by_category}
            label={row.category}
            value={row.total}
            max={@category_max}
          />
        </div>
      </div>

      <div class="rounded-box border border-base-300 p-4">
        <h2 class="mb-4 text-lg font-semibold">Spend over time</h2>
        <Charts.line_chart points={@over_time} />
      </div>

      <div class="rounded-box border border-base-300 p-4">
        <h2 class="mb-4 text-lg font-semibold">Transactions (most recent 50 in range)</h2>
        <.table id="dashboard-transactions" rows={@transactions}>
          <:col :let={t} label="Date">{t.date}</:col>
          <:col :let={t} label="Description">{t.description}</:col>
          <:col :let={t} label="Direction">{t.direction}</:col>
          <:col :let={t} label="Amount">{t.amount} {t.currency.code}</:col>
          <:col :let={t} label="Base (SCR)">{t.amount_base}</:col>
          <:col :let={t} label="Envelope">{t.budget_envelope && t.budget_envelope.name}</:col>
          <:col :let={t} label="Vendor">{t.vendor && t.vendor.name}</:col>
        </.table>
      </div>
    </div>
    """
  end
end
