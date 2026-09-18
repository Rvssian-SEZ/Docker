defmodule CofferWeb.BudgetLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Budgets
  alias Coffer.Budgets.{Category, Envelope}
  alias Coffer.FiscalYear
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :budget_envelope) do
      current_year = FiscalYear.current_year()

      {:ok,
       socket
       |> assign(:date_from, FiscalYear.start_date(current_year))
       |> assign(:date_to, FiscalYear.end_date(current_year))
       # Defaults true for a first-ever/disconnected render (no localStorage
       # access yet); the .BudgetsExpandPref hook pushes the real stored
       # preference right after mount if one exists, which then sticks for
       # the rest of the connection — unlike a client-only DOM tweak, this
       # survives LiveView's own reconnect re-render since the server now
       # actually knows the preference instead of hardcoding `open` and
       # letting a later diff silently patch it back.
       |> assign(:expanded, true)
       |> refresh_grouped_envelopes()
       |> assign(:editing_category_id, nil)
       |> assign_categories()
       |> assign(:category_form, to_form(Budgets.change_category(%Category{})))
       |> assign(:show_category_quickadd, false)
       |> assign(:category_quickadd_form, to_form(Budgets.change_category(%Category{})))}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view budgets.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if socket.assigns.live_action in [:new, :edit] and
         not Policy.can?(socket.assigns.current_user, action, :budget_envelope) do
      {:noreply,
       socket
       |> put_flash(:error, "You're not authorized to do that.")
       |> push_navigate(to: ~p"/budgets")}
    else
      {:noreply, apply_action(socket, socket.assigns.live_action, params)}
    end
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    envelope = Budgets.get_envelope!(id)

    socket
    |> assign(:page_title, "Edit envelope")
    |> assign(:envelope, envelope)
    |> assign(:form, to_form(Budgets.change_envelope(envelope)))
    |> reset_category_quickadd()
  end

  defp apply_action(socket, :new, params) do
    envelope = prefill_from_envelope(params["duplicate_from"])
    title = if params["duplicate_from"], do: "Duplicate envelope", else: "New envelope"

    socket
    |> assign(:page_title, title)
    |> assign(:envelope, envelope)
    |> assign(:form, to_form(Budgets.change_envelope(envelope)))
    |> reset_category_quickadd()
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Budgets")
    |> assign(:envelope, nil)
  end

  # "Duplicate" on an envelope row pre-fills New envelope from it — for the
  # user's stated workflow of setting up next year's budget from this
  # year's, so the copy defaults to the source's own fiscal year + 1 (not
  # just "current year"), while everything stays editable before saving.
  # Mirrors CofferWeb.LedgerLive.Index's prefill_from_contract/1.
  defp prefill_from_envelope(nil), do: %Envelope{fiscal_year: FiscalYear.current_year()}

  defp prefill_from_envelope(envelope_id) do
    source = Budgets.get_envelope!(envelope_id)

    %Envelope{
      name: source.name,
      description: source.description,
      fiscal_year: source.fiscal_year + 1,
      allocated_amount: source.allocated_amount,
      category_id: source.category_id,
      active: true
    }
  end

  @impl true
  def handle_event("validate", %{"envelope" => params}, socket) do
    form =
      socket.assigns.envelope
      |> Budgets.change_envelope(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"envelope" => params}, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if Policy.can?(socket.assigns.current_user, action, :budget_envelope) do
      save_envelope(socket, socket.assigns.live_action, params)
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to do that.")}
    end
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :budget_envelope) do
      envelope = Budgets.get_envelope!(id)

      case Budgets.delete_envelope(envelope, socket.assigns.current_user) do
        {:ok, _envelope} ->
          {:noreply,
           socket
           |> put_flash(:info, "Envelope deleted.")
           |> refresh_grouped_envelopes()}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete envelope.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete envelopes.")}
    end
  end

  def handle_event("validate_category", %{"category" => params}, socket) do
    form =
      socket
      |> category_form_source()
      |> Budgets.change_category(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :category_form, form)}
  end

  def handle_event("save_category", %{"category" => params}, socket) do
    case socket.assigns.editing_category_id do
      nil -> create_category(socket, params)
      id -> update_category(socket, id, params)
    end
  end

  def handle_event("edit_category", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :update, :budget_category) do
      category = Budgets.get_category!(id)

      {:noreply,
       socket
       |> assign(:editing_category_id, category.id)
       |> assign(:category_form, to_form(Budgets.change_category(category)))}
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to edit categories.")}
    end
  end

  def handle_event("cancel_edit_category", _params, socket) do
    {:noreply,
     socket
     |> assign(:editing_category_id, nil)
     |> assign(:category_form, to_form(Budgets.change_category(%Category{})))}
  end

  def handle_event("delete_category", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :budget_category) do
      category = Budgets.get_category!(id)

      case Budgets.delete_category(category, socket.assigns.current_user) do
        {:ok, _category} ->
          {:noreply,
           socket
           |> put_flash(:info, "Category deleted.")
           |> assign_categories()}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete category.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete categories.")}
    end
  rescue
    Ecto.ConstraintError ->
      {:noreply,
       put_flash(socket, :error, "That category is still used by one or more envelopes.")}
  end

  # Lets a category get created without leaving the envelope popup — the
  # quickadd form is deliberately a separate `@category_quickadd_form`
  # rather than reusing `@category_form` (the persistent category-management
  # form below the envelope table), since both can be on screen at once and
  # sharing state between them would cross-contaminate whatever the user was
  # typing in either one.
  def handle_event("toggle_category_quickadd", _params, socket) do
    {:noreply,
     socket
     |> assign(:show_category_quickadd, not socket.assigns.show_category_quickadd)
     |> assign(:category_quickadd_form, to_form(Budgets.change_category(%Category{})))}
  end

  def handle_event("validate_category_quickadd", %{"category" => params}, socket) do
    form =
      %Category{}
      |> Budgets.change_category(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :category_quickadd_form, form)}
  end

  def handle_event("quickadd_category", %{"category" => params}, socket) do
    if Policy.can?(socket.assigns.current_user, :create, :budget_category) do
      case Budgets.create_category(params, socket.assigns.current_user) do
        {:ok, category} ->
          envelope_form =
            socket.assigns.form.source
            |> Ecto.Changeset.put_change(:category_id, category.id)
            |> Map.put(:action, :validate)
            |> to_form()

          {:noreply,
           socket
           |> put_flash(:info, "Category added.")
           |> assign_categories()
           |> assign(:form, envelope_form)
           |> reset_category_quickadd()}

        {:error, changeset} ->
          {:noreply, assign(socket, :category_quickadd_form, to_form(changeset))}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to add categories.")}
    end
  end

  def handle_event("start_new_fy", _params, socket) do
    if Policy.can?(socket.assigns.current_user, :trigger_rollover, :budget_envelope) do
      target_year = FiscalYear.current_year()

      case Budgets.rollover_fiscal_year(target_year, socket.assigns.current_user.id) do
        {:ok, :already_rolled_over} ->
          {:noreply,
           put_flash(socket, :info, "FY#{target_year} envelopes already exist — nothing to do.")}

        {:ok, :no_prior_year_envelopes} ->
          {:noreply,
           put_flash(
             socket,
             :error,
             "No prior-year envelopes found to roll over from."
           )}

        {:ok, created} ->
          {:noreply,
           socket
           |> put_flash(
             :info,
             "Started FY#{target_year}: #{length(created)} envelope(s) created."
           )
           |> refresh_grouped_envelopes()}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not roll over to the new fiscal year.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to start a new fiscal year.")}
    end
  end

  # `collapsed` arrives as a real boolean (not a stringified phx-value) since
  # the buttons/hook send it via JS.push's `value:`/pushEvent's JSON payload.
  def handle_event("set_expand_pref", %{"collapsed" => collapsed}, socket) do
    {:noreply,
     socket
     |> assign(:expanded, not collapsed)
     |> push_event("persist_expand_pref", %{collapsed: collapsed})}
  end

  def handle_event("filter_range", params, socket) do
    {:noreply,
     socket
     |> assign(:date_from, parse_date(params["date_from"]) || socket.assigns.date_from)
     |> assign(:date_to, parse_date(params["date_to"]) || socket.assigns.date_to)
     |> refresh_grouped_envelopes()}
  end

  def handle_event("reset_range_to_current_year", _params, socket) do
    current_year = FiscalYear.current_year()

    {:noreply,
     socket
     |> assign(:date_from, FiscalYear.start_date(current_year))
     |> assign(:date_to, FiscalYear.end_date(current_year))
     |> refresh_grouped_envelopes()}
  end

  defp parse_date(nil), do: nil
  defp parse_date(""), do: nil

  defp parse_date(str) do
    case Date.from_iso8601(str) do
      {:ok, date} -> date
      _ -> nil
    end
  end

  defp reset_category_quickadd(socket) do
    socket
    |> assign(:show_category_quickadd, false)
    |> assign(:category_quickadd_form, to_form(Budgets.change_category(%Category{})))
  end

  defp category_form_source(socket) do
    case socket.assigns.editing_category_id do
      nil -> %Category{}
      id -> Budgets.get_category!(id)
    end
  end

  defp create_category(socket, params) do
    if Policy.can?(socket.assigns.current_user, :create, :budget_category) do
      case Budgets.create_category(params, socket.assigns.current_user) do
        {:ok, _category} ->
          {:noreply,
           socket
           |> put_flash(:info, "Category added.")
           |> assign_categories()
           |> assign(:category_form, to_form(Budgets.change_category(%Category{})))}

        {:error, changeset} ->
          {:noreply, assign(socket, :category_form, to_form(changeset))}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to add categories.")}
    end
  end

  defp update_category(socket, id, params) do
    if Policy.can?(socket.assigns.current_user, :update, :budget_category) do
      category = Budgets.get_category!(id)

      case Budgets.update_category(category, params, socket.assigns.current_user) do
        {:ok, _category} ->
          {:noreply,
           socket
           |> put_flash(:info, "Category updated.")
           |> assign(:editing_category_id, nil)
           |> assign_categories()
           |> assign(:category_form, to_form(Budgets.change_category(%Category{})))}

        {:error, changeset} ->
          {:noreply, assign(socket, :category_form, to_form(changeset))}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to edit categories.")}
    end
  end

  defp assign_categories(socket) do
    categories = Budgets.list_categories()

    socket
    |> assign(:categories, categories)
    |> assign(:category_tree, Budgets.list_categories_tree())
    |> assign(
      :category_options,
      Enum.map(categories, &{Budgets.category_path_label(&1, categories), &1.id})
    )
    # A category rename/reparent changes how the grouped envelope view
    # should look (name, indentation) even though no envelope itself
    # changed, so every category mutation refreshes this too.
    |> refresh_grouped_envelopes()
  end

  defp negative_class(%Decimal{} = amount) do
    if Decimal.negative?(amount), do: "text-error font-semibold"
  end

  defp refresh_grouped_envelopes(socket) do
    envelopes = Budgets.list_envelopes_in_range(socket.assigns.date_from, socket.assigns.date_to)
    assign(socket, :grouped_envelopes, Budgets.envelopes_grouped_by_category(envelopes))
  end

  # A category can't become its own descendant's child (the changeset
  # already rejects that server-side) — drop those options client-side too
  # so an editor isn't offered choices that would just bounce back as errors.
  defp parent_options(category_options, _categories, nil), do: category_options

  defp parent_options(category_options, categories, editing_id) do
    disallowed = Budgets.category_and_descendant_ids(editing_id, categories)
    Enum.reject(category_options, fn {_label, id} -> id in disallowed end)
  end

  defp save_envelope(socket, :edit, params) do
    case Budgets.update_envelope(socket.assigns.envelope, params, socket.assigns.current_user) do
      {:ok, _envelope} ->
        {:noreply,
         socket
         |> put_flash(:info, "Envelope updated.")
         |> push_navigate(to: ~p"/budgets")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_envelope(socket, :new, params) do
    case Budgets.create_envelope(params, socket.assigns.current_user) do
      {:ok, _envelope} ->
        {:noreply,
         socket
         |> put_flash(:info, "Envelope created.")
         |> push_navigate(to: ~p"/budgets")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-4xl py-12">
      <.header>
        Budgets
        <:actions>
          <.link href={~p"/budgets/export.csv"} class="btn btn-outline">Export CSV</.link>
          <.link
            :if={Policy.can?(@current_user, :trigger_rollover, :budget_envelope)}
            phx-click="start_new_fy"
            data-confirm="Start the new fiscal year? This copies active envelopes from the most recent prior year — it won't touch existing years."
            class="btn btn-outline"
          >
            Start new FY
          </.link>
          <.link
            :if={Policy.can?(@current_user, :create, :budget_envelope)}
            href={~p"/budgets/new"}
            class="btn btn-primary"
          >
            New envelope
          </.link>
        </:actions>
      </.header>

      <form phx-change="filter_range" class="mt-4 flex flex-wrap items-end gap-4">
        <.input type="date" name="date_from" label="From" value={@date_from} />
        <.input type="date" name="date_to" label="To" value={@date_to} />
        <button type="button" phx-click="reset_range_to_current_year" class="btn btn-ghost btn-sm">
          Reset to current year
        </button>
      </form>

      <p class="mt-2 text-sm text-base-content/60">
        Showing envelopes with a fiscal year overlapping {@date_from} to {@date_to}.
      </p>

      <p :if={@grouped_envelopes == []} class="text-sm text-base-content/60">
        No envelopes in this range.
      </p>

      <div :if={@grouped_envelopes != []} class="mt-2 flex items-center gap-2">
        <div id="budgets-expand-pref" phx-hook=".BudgetsExpandPref"></div>
        <button
          type="button"
          phx-click={JS.push("set_expand_pref", value: %{collapsed: false})}
          class="btn btn-outline btn-sm"
        >
          Expand all
        </button>
        <button
          type="button"
          phx-click={JS.push("set_expand_pref", value: %{collapsed: true})}
          class="btn btn-outline btn-sm"
        >
          Collapse all
        </button>
        <span class="text-xs text-base-content/50">
          (also remembered as the default next time you open this page)
        </span>
      </div>

      <script :type={Phoenix.LiveView.ColocatedHook} name=".BudgetsExpandPref">
        // A plain client-side DOM tweak isn't enough here — LiveView
        // re-renders this page server-side on the reconnect right after the
        // initial HTTP load, and that render would silently patch any
        // manually-toggled `open` attribute right back to whatever the
        // server last rendered. So this hook pushes the stored preference
        // to the server on mount instead (see handle_event("set_expand_pref",
        // ...) in budget_live/index.ex), which is what actually makes it
        // stick — and just mirrors back whatever the server later confirms
        // via push_event, rather than writing to localStorage itself, so
        // the two can never drift out of sync.
        export default {
          mounted() {
            const KEY = "phx:budgets-collapsed-default"
            const stored = localStorage.getItem(KEY)
            if (stored !== null) {
              this.pushEvent("set_expand_pref", {collapsed: stored === "true"})
            }
            this.handleEvent("persist_expand_pref", ({collapsed}) => {
              localStorage.setItem(KEY, collapsed ? "true" : "false")
            })
          }
        }
      </script>

      <div class="mt-2 space-y-2">
        <.category_group
          :for={group <- @grouped_envelopes}
          group={group}
          current_user={@current_user}
          expanded={@expanded}
        />
      </div>

      <.link href={~p"/"} class="link mt-6 inline-block">&larr; Back</.link>

      <.modal_form
        :if={@live_action in [:new, :edit]}
        title={@page_title}
        cancel_href={~p"/budgets"}
      >
        <.form for={@form} id="envelope-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:name]} label="Name" />
          <.input field={@form[:description]} type="textarea" label="Description" />
          <.input field={@form[:fiscal_year]} type="number" step="1" label="Fiscal year" />
          <.input field={@form[:allocated_amount]} type="number" step="0.01" label="Allocated (SCR)" />
          <.input
            field={@form[:category_id]}
            type="select"
            label="Category"
            options={@category_options}
          />
          <button type="button" phx-click="toggle_category_quickadd" class="link text-xs">
            {if @show_category_quickadd, do: "Cancel new category", else: "+ Add a missing category"}
          </button>
          <.input field={@form[:active]} type="checkbox" label="Active" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/budgets"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>

        <.form
          :if={@show_category_quickadd}
          for={@category_quickadd_form}
          id="category-quickadd-form"
          phx-change="validate_category_quickadd"
          phx-submit="quickadd_category"
          class="mt-3 space-y-2 rounded-box border border-base-300 bg-base-200/50 p-3"
        >
          <p class="text-sm font-medium">New category</p>
          <.input field={@category_quickadd_form[:name]} label="Name" />
          <.input
            field={@category_quickadd_form[:parent_id]}
            type="select"
            label="Parent (optional)"
            prompt="None (top-level)"
            options={@category_options}
          />
          <div class="flex justify-end">
            <.button phx-disable-with="Adding...">Add category</.button>
          </div>
        </.form>
      </.modal_form>

      <div class="mt-12 max-w-sm">
        <h2 class="text-lg font-semibold">Categories</h2>

        <ul class="mt-2 space-y-1">
          <li :for={c <- @category_tree} class="flex items-center justify-between gap-2">
            <span style={"padding-left: #{c.depth * 1.25}rem"}>
              <span :if={c.depth > 0} class="text-base-content/40">&#8627;</span>
              {c.name}
            </span>
            <span class="flex gap-2 text-sm">
              <button
                :if={Policy.can?(@current_user, :update, :budget_category)}
                phx-click="edit_category"
                phx-value-id={c.id}
                class="link"
              >
                Edit
              </button>
              <button
                :if={Policy.can?(@current_user, :delete, :budget_category)}
                phx-click="delete_category"
                phx-value-id={c.id}
                data-confirm={"Delete category \"#{c.name}\"? Any subcategories become top-level."}
                class="link link-error"
              >
                Delete
              </button>
            </span>
          </li>
        </ul>

        <.form
          :if={
            Policy.can?(@current_user, :create, :budget_category) or
              Policy.can?(@current_user, :update, :budget_category)
          }
          for={@category_form}
          id="category-form"
          phx-change="validate_category"
          phx-submit="save_category"
          class="mt-4 space-y-2"
        >
          <.input
            field={@category_form[:name]}
            label={if @editing_category_id, do: "Edit category", else: "New category"}
          />
          <.input
            field={@category_form[:parent_id]}
            type="select"
            label="Parent (optional)"
            prompt="None (top-level)"
            options={parent_options(@category_options, @categories, @editing_category_id)}
          />
          <footer class="flex justify-end gap-2">
            <.link :if={@editing_category_id} phx-click="cancel_edit_category" class="btn btn-ghost">
              Cancel
            </.link>
            <.button phx-disable-with="Saving...">
              {if @editing_category_id, do: "Save", else: "Add"}
            </.button>
          </footer>
        </.form>
      </div>
    </div>
    """
  end

  # Renders one category's envelope table plus, nested *inside* the same
  # <details> (not as a same-level sibling), every child category's own
  # group — calling itself recursively for `@group.children`. This is what
  # actually makes a subcategory appear inside its parent's box: collapsing
  # the parent hides its whole subtree for free, since a nested <details>
  # simply isn't rendered while its ancestor is closed.
  attr :group, :map, required: true
  attr :current_user, :map, required: true
  attr :expanded, :boolean, required: true

  defp category_group(assigns) do
    ~H"""
    <details open={@expanded} class="budget-group overflow-hidden rounded-box border border-base-300">
      <summary class="flex flex-wrap cursor-pointer items-center justify-between gap-2 bg-base-200 px-4 py-2 marker:text-base-content/40">
        <span class="font-semibold">{@group.category.name}</span>
        <span class="text-sm text-base-content/70">
          Allocated {format_money(@group.allocated_total)} SCR &middot; Remaining
          <span class={negative_class(@group.remaining_total)}>
            {format_money(@group.remaining_total)} SCR
          </span>
        </span>
      </summary>

      <.table
        :if={@group.envelopes != []}
        id={"budget-envelopes-#{@group.category.id}"}
        rows={@group.envelopes}
      >
        <:col :let={e} label="FY">{e.fiscal_year}</:col>
        <:col :let={e} label="Name">{e.name}</:col>
        <:col :let={e} label="Allocated (SCR)">{format_money(e.allocated_amount)}</:col>
        <:col :let={e} label="Remaining (SCR)">
          <% remaining = Budgets.envelope_remaining(e) %>
          <span class={negative_class(remaining)}>{format_money(remaining)}</span>
        </:col>
        <:col :let={e} label="Active?">{e.active}</:col>
        <:action :let={e}>
          <.link
            :if={Policy.can?(@current_user, :update, :budget_envelope)}
            href={~p"/budgets/#{e.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={e}>
          <.link
            :if={Policy.can?(@current_user, :create, :budget_envelope)}
            href={~p"/budgets/new?duplicate_from=#{e.id}"}
            class="link"
          >
            Duplicate
          </.link>
        </:action>
        <:action :let={e}>
          <.link
            :if={Policy.can?(@current_user, :delete, :budget_envelope)}
            phx-click="delete"
            phx-value-id={e.id}
            data-confirm="Delete this envelope?"
            class="link link-error"
          >
            Delete
          </.link>
        </:action>
      </.table>
      <p
        :if={@group.envelopes == [] and @group.children == []}
        class="px-4 py-3 text-sm text-base-content/50"
      >
        No envelopes directly in this category (total above is from subcategories).
      </p>

      <div :if={@group.children != []} class="space-y-2 border-t border-base-300 bg-base-100 p-2 pl-6">
        <.category_group
          :for={child <- @group.children}
          group={child}
          current_user={@current_user}
          expanded={@expanded}
        />
      </div>
    </details>
    """
  end
end
