defmodule CofferWeb.BudgetLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Budgets
  alias Coffer.Budgets.{Category, Envelope}
  alias Coffer.FiscalYear
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :budget_envelope) do
      {:ok,
       socket
       |> assign(:envelopes, Budgets.list_envelopes())
       |> assign(:editing_category_id, nil)
       |> assign_categories()
       |> assign(:category_form, to_form(Budgets.change_category(%Category{})))}
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
  end

  defp apply_action(socket, :new, _params) do
    envelope = %Envelope{fiscal_year: FiscalYear.current_year()}

    socket
    |> assign(:page_title, "New envelope")
    |> assign(:envelope, envelope)
    |> assign(:form, to_form(Budgets.change_envelope(envelope)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Budgets")
    |> assign(:envelope, nil)
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
           |> assign(:envelopes, Budgets.list_envelopes())}

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
           |> assign(:envelopes, Budgets.list_envelopes())}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not roll over to the new fiscal year.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to start a new fiscal year.")}
    end
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

      <.table id="budget-envelopes" rows={@envelopes}>
        <:col :let={e} label="FY">{e.fiscal_year}</:col>
        <:col :let={e} label="Name">{e.name}</:col>
        <:col :let={e} label="Category">{e.category.name}</:col>
        <:col :let={e} label="Allocated (SCR)">{e.allocated_amount}</:col>
        <:col :let={e} label="Remaining (SCR)">{Budgets.envelope_remaining(e)}</:col>
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
          <.input field={@form[:active]} type="checkbox" label="Active" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/budgets"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
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
end
