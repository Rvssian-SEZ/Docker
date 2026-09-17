defmodule CofferWeb.RoleMappingLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Accounts
  alias Coffer.Accounts.RoleMapping
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :role_mapping) do
      {:ok, assign(socket, :role_mappings, Accounts.list_role_mappings())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view role mappings.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if socket.assigns.live_action in [:new, :edit] and
         not Policy.can?(socket.assigns.current_user, action, :role_mapping) do
      {:noreply,
       socket
       |> put_flash(:error, "You're not authorized to do that.")
       |> push_navigate(to: ~p"/admin/role_mappings")}
    else
      {:noreply, apply_action(socket, socket.assigns.live_action, params)}
    end
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    role_mapping = Accounts.get_role_mapping!(id)

    socket
    |> assign(:page_title, "Edit role mapping")
    |> assign(:role_mapping, role_mapping)
    |> assign(:form, to_form(Accounts.change_role_mapping(role_mapping)))
  end

  defp apply_action(socket, :new, _params) do
    role_mapping = %RoleMapping{}

    socket
    |> assign(:page_title, "New role mapping")
    |> assign(:role_mapping, role_mapping)
    |> assign(:form, to_form(Accounts.change_role_mapping(role_mapping)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Role mappings")
    |> assign(:role_mapping, nil)
  end

  @impl true
  def handle_event("validate", %{"role_mapping" => params}, socket) do
    form =
      socket.assigns.role_mapping
      |> Accounts.change_role_mapping(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"role_mapping" => params}, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if Policy.can?(socket.assigns.current_user, action, :role_mapping) do
      save_role_mapping(socket, socket.assigns.live_action, params)
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to do that.")}
    end
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :role_mapping) do
      role_mapping = Accounts.get_role_mapping!(id)

      case Accounts.delete_role_mapping(role_mapping, socket.assigns.current_user) do
        {:ok, _role_mapping} ->
          {:noreply,
           socket
           |> put_flash(:info, "Role mapping deleted.")
           |> assign(:role_mappings, Accounts.list_role_mappings())}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete role mapping.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete role mappings.")}
    end
  end

  defp save_role_mapping(socket, :edit, params) do
    case Accounts.update_role_mapping(
           socket.assigns.role_mapping,
           params,
           socket.assigns.current_user
         ) do
      {:ok, _role_mapping} ->
        {:noreply,
         socket
         |> put_flash(:info, "Role mapping updated.")
         |> push_navigate(to: ~p"/admin/role_mappings")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_role_mapping(socket, :new, params) do
    case Accounts.create_role_mapping(params, socket.assigns.current_user) do
      {:ok, _role_mapping} ->
        {:noreply,
         socket
         |> put_flash(:info, "Role mapping created.")
         |> push_navigate(to: ~p"/admin/role_mappings")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl py-12">
      <.header>
        Role mappings
        <:actions>
          <.link href={~p"/admin/role_mappings/export.csv"} class="btn btn-outline">
            Export CSV
          </.link>
          <.link
            :if={Policy.can?(@current_user, :create, :role_mapping)}
            href={~p"/admin/role_mappings/new"}
            class="btn btn-primary"
          >
            New mapping
          </.link>
        </:actions>
      </.header>

      <.table id="role-mappings" rows={@role_mappings}>
        <:col :let={rm} label="Authentik group">{rm.authentik_group}</:col>
        <:col :let={rm} label="App role">{rm.app_role}</:col>
        <:action :let={rm}>
          <.link
            :if={Policy.can?(@current_user, :update, :role_mapping)}
            href={~p"/admin/role_mappings/#{rm.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={rm}>
          <.link
            :if={Policy.can?(@current_user, :delete, :role_mapping)}
            phx-click="delete"
            phx-value-id={rm.id}
            data-confirm="Delete this role mapping?"
            class="link link-error"
          >
            Delete
          </.link>
        </:action>
      </.table>

      <.link href={~p"/"} class="link mt-6 inline-block">&larr; Back</.link>

      <div
        :if={@live_action in [:new, :edit]}
        class="mt-8 max-w-sm rounded-box border border-base-300 p-6"
      >
        <h2 class="text-lg font-semibold">{@page_title}</h2>

        <.form for={@form} id="role-mapping-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:authentik_group]} label="Authentik group" />
          <.input
            field={@form[:app_role]}
            type="select"
            label="App role"
            options={Enum.map(Coffer.Accounts.User.roles(), &{Phoenix.Naming.humanize(&1), &1})}
          />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/admin/role_mappings"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>
      </div>
    </div>
    """
  end
end
