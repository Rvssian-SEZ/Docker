defmodule CofferWeb.AuditLogLive.Index do
  use CofferWeb, :live_view

  alias Coffer.AuditLog
  alias Coffer.AuditLog.Presenter
  alias Coffer.Authorization.Policy
  alias Coffer.{Accounts, Budgets, Contracts, Currencies, Inventory, Vendors}

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :audit_log) do
      filters = %{"resource_type" => "", "action" => "", "user_id" => ""}

      {:ok,
       socket
       |> assign(:page_title, "Audit log")
       |> assign(:filters, filters)
       |> assign(:resource_types, AuditLog.distinct_resource_types())
       |> assign(:users, Accounts.list_users())
       |> assign(:ref_lookup, build_ref_lookup())
       |> assign(:entries, AuditLog.list_entries())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view the audit log.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_event("filter", params, socket) do
    filters = %{
      "resource_type" => params["resource_type"] || "",
      "action" => params["action"] || "",
      "user_id" => params["user_id"] || ""
    }

    entries =
      AuditLog.list_entries(%{
        resource_type: filters["resource_type"],
        action: filters["action"],
        user_id: filters["user_id"]
      })

    {:noreply, socket |> assign(:filters, filters) |> assign(:entries, entries)}
  end

  # Small reference tables, resolved once so update diffs can show "USD"
  # instead of "currency_id: 3" — see moduledoc on Coffer.AuditLog.Presenter.
  defp build_ref_lookup do
    users = Accounts.list_users() |> Map.new(&{&1.id, &1.name})
    categories = Budgets.list_categories() |> Map.new(&{&1.id, &1.name})

    %{
      "currency_id" => Currencies.list_currencies() |> Map.new(&{&1.id, &1.code}),
      "vendor_id" => Vendors.list_vendors() |> Map.new(&{&1.id, &1.name}),
      "budget_envelope_id" => Budgets.list_envelopes() |> Map.new(&{&1.id, &1.name}),
      "contract_id" => Contracts.list_contracts() |> Map.new(&{&1.id, &1.name}),
      "inventory_item_id" => Inventory.list_items() |> Map.new(&{&1.id, &1.name}),
      "category_id" => categories,
      "parent_id" => categories,
      "user_id" => users,
      "uploaded_by_id" => users
    }
  end

  defp entry_summary(entry) do
    actor = (entry.user && entry.user.name) || "System"
    resource = Presenter.resource_type_label(entry.resource_type)
    label = Presenter.resource_label(entry.before, entry.after)

    subject = if label, do: "#{resource}: #{label}", else: "#{resource} ##{entry.resource_id}"

    "#{actor} #{Presenter.action_label(entry.action)} #{subject}"
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-5xl py-12">
      <.header>
        Audit log
        <:actions>
          <.link
            :if={Policy.can?(@current_user, :export, :audit_log)}
            href={~p"/admin/audit-log/export.csv"}
            class="btn btn-outline"
          >
            Export CSV
          </.link>
        </:actions>
      </.header>

      <form phx-change="filter" class="mt-4 flex flex-wrap items-end gap-3">
        <fieldset class="fieldset">
          <label class="mb-1 text-sm">Resource type</label>
          <select name="resource_type" class="select select-bordered">
            <option value="" selected={@filters["resource_type"] == ""}>All</option>
            <option
              :for={type <- @resource_types}
              value={type}
              selected={@filters["resource_type"] == type}
            >
              {Presenter.resource_type_label(type)}
            </option>
          </select>
        </fieldset>

        <fieldset class="fieldset">
          <label class="mb-1 text-sm">Action</label>
          <select name="action" class="select select-bordered">
            <option value="" selected={@filters["action"] == ""}>All</option>
            <option :for={a <- ~w(create update delete)} value={a} selected={@filters["action"] == a}>
              {Phoenix.Naming.humanize(a)}
            </option>
          </select>
        </fieldset>

        <fieldset class="fieldset">
          <label class="mb-1 text-sm">User</label>
          <select name="user_id" class="select select-bordered">
            <option value="" selected={@filters["user_id"] == ""}>All</option>
            <option
              :for={u <- @users}
              value={u.id}
              selected={@filters["user_id"] == to_string(u.id)}
            >
              {u.name}
            </option>
          </select>
        </fieldset>
      </form>

      <p :if={@entries == []} class="mt-8 text-sm text-base-content/60">
        No matching audit log entries.
      </p>

      <ul class="mt-6 space-y-2">
        <li :for={e <- @entries} class="rounded-box border border-base-300 p-4">
          <div class="flex flex-wrap items-center gap-2">
            <span class={["badge badge-sm", Presenter.action_badge_class(e.action)]}>
              {Phoenix.Naming.humanize(e.action)}
            </span>
            <span class="text-sm">{entry_summary(e)}</span>
            <span class="ml-auto text-xs text-base-content/60">
              {Calendar.strftime(e.inserted_at, "%Y-%m-%d %H:%M UTC")}
            </span>
          </div>

          <% diffs = Presenter.changes(e.action, e.before, e.after, @ref_lookup) %>
          <details :if={diffs != []} class="mt-2">
            <summary class="cursor-pointer text-xs text-base-content/60 hover:text-base-content">
              {if e.action == :update, do: "What changed (#{length(diffs)})", else: "Details"}
            </summary>
            <ul class="mt-2 space-y-1 pl-4 text-sm">
              <li :for={diff <- diffs}>
                <%= case diff do %>
                  <% {label, old, new} -> %>
                    <span class="text-base-content/60">{label}:</span>
                    <del class="text-base-content/50">{old}</del>
                    <span aria-hidden="true">&rarr;</span>
                    <ins class="font-medium no-underline">{new}</ins>
                  <% {label, value} -> %>
                    <span class="text-base-content/60">{label}:</span> {value}
                <% end %>
              </li>
            </ul>
          </details>
        </li>
      </ul>

      <.link href={~p"/"} class="link mt-6 inline-block">&larr; Back</.link>
    </div>
    """
  end
end
