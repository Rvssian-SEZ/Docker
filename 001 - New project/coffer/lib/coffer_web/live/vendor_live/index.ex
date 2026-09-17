defmodule CofferWeb.VendorLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Vendors
  alias Coffer.Vendors.Vendor
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :vendor) do
      {:ok, assign(socket, :vendors, Vendors.list_vendors())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view vendors.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    {:noreply, apply_action(socket, socket.assigns.live_action, params)}
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    vendor = Vendors.get_vendor!(id)

    socket
    |> assign(:page_title, "Edit vendor")
    |> assign(:vendor, vendor)
    |> assign(:form, to_form(Vendors.change_vendor(vendor)))
  end

  defp apply_action(socket, :new, _params) do
    vendor = %Vendor{}

    socket
    |> assign(:page_title, "New vendor")
    |> assign(:vendor, vendor)
    |> assign(:form, to_form(Vendors.change_vendor(vendor)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Vendors")
    |> assign(:vendor, nil)
  end

  @impl true
  def handle_event("validate", %{"vendor" => params}, socket) do
    form =
      socket.assigns.vendor
      |> Vendors.change_vendor(build_attrs(params))
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"vendor" => params}, socket) do
    save_vendor(socket, socket.assigns.live_action, build_attrs(params))
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :vendor) do
      vendor = Vendors.get_vendor!(id)

      case Vendors.delete_vendor(vendor, socket.assigns.current_user) do
        {:ok, _vendor} ->
          {:noreply,
           socket
           |> put_flash(:info, "Vendor deleted.")
           |> assign(:vendors, Vendors.list_vendors())}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete vendor.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete vendors.")}
    end
  end

  # `email`/`phone` are plain form fields, not real Vendor columns — folded
  # into the `contact_info` map (spec §4.5) before hitting the changeset.
  defp build_attrs(params) do
    {email, params} = Map.pop(params, "email", "")
    {phone, params} = Map.pop(params, "phone", "")
    Map.put(params, "contact_info", %{"email" => email, "phone" => phone})
  end

  defp save_vendor(socket, :edit, attrs) do
    case Vendors.update_vendor(socket.assigns.vendor, attrs, socket.assigns.current_user) do
      {:ok, _vendor} ->
        {:noreply,
         socket
         |> put_flash(:info, "Vendor updated.")
         |> push_navigate(to: ~p"/vendors")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_vendor(socket, :new, attrs) do
    case Vendors.create_vendor(attrs, socket.assigns.current_user) do
      {:ok, _vendor} ->
        {:noreply,
         socket
         |> put_flash(:info, "Vendor created.")
         |> push_navigate(to: ~p"/vendors")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl py-12">
      <.header>
        Vendors
        <:actions>
          <.link href={~p"/vendors/export.csv"} class="btn btn-outline">Export CSV</.link>
          <.link
            :if={Policy.can?(@current_user, :create, :vendor)}
            href={~p"/vendors/new"}
            class="btn btn-primary"
          >
            New vendor
          </.link>
        </:actions>
      </.header>

      <.table id="vendors" rows={@vendors}>
        <:col :let={v} label="Name">{v.name}</:col>
        <:col :let={v} label="Email">{v.contact_info["email"]}</:col>
        <:col :let={v} label="Phone">{v.contact_info["phone"]}</:col>
        <:action :let={v}>
          <.link
            :if={Policy.can?(@current_user, :update, :vendor)}
            href={~p"/vendors/#{v.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={v}>
          <.link
            :if={Policy.can?(@current_user, :delete, :vendor)}
            phx-click="delete"
            phx-value-id={v.id}
            data-confirm="Delete this vendor?"
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

        <.form for={@form} id="vendor-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:name]} label="Name" />
          <fieldset class="fieldset">
            <legend class="fieldset-legend">Email</legend>
            <input
              type="text"
              name="vendor[email]"
              value={@vendor.contact_info["email"]}
              class="input w-full"
            />
          </fieldset>
          <fieldset class="fieldset">
            <legend class="fieldset-legend">Phone</legend>
            <input
              type="text"
              name="vendor[phone]"
              value={@vendor.contact_info["phone"]}
              class="input w-full"
            />
          </fieldset>
          <.input field={@form[:notes]} type="textarea" label="Notes" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/vendors"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>
      </div>
    </div>
    """
  end
end
