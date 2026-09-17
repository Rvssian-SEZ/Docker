defmodule CofferWeb.CurrencyLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Currencies
  alias Coffer.Currencies.Currency
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :currency) do
      {:ok, assign(socket, :currencies, Currencies.list_currencies())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view currencies.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if socket.assigns.live_action in [:new, :edit] and
         not Policy.can?(socket.assigns.current_user, action, :currency) do
      {:noreply,
       socket
       |> put_flash(:error, "You're not authorized to do that.")
       |> push_navigate(to: ~p"/admin/currencies")}
    else
      {:noreply, apply_action(socket, socket.assigns.live_action, params)}
    end
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    currency = Currencies.get_currency!(id)

    socket
    |> assign(:page_title, "Edit currency")
    |> assign(:currency, currency)
    |> assign(:form, to_form(Currencies.change_currency(currency)))
  end

  defp apply_action(socket, :new, _params) do
    currency = %Currency{}

    socket
    |> assign(:page_title, "New currency")
    |> assign(:currency, currency)
    |> assign(:form, to_form(Currencies.change_currency(currency)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Currencies")
    |> assign(:currency, nil)
  end

  @impl true
  def handle_event("validate", %{"currency" => params}, socket) do
    form =
      socket.assigns.currency
      |> Currencies.change_currency(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"currency" => params}, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if Policy.can?(socket.assigns.current_user, action, :currency) do
      save_currency(socket, socket.assigns.live_action, params)
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to do that.")}
    end
  end

  defp save_currency(socket, :edit, params) do
    case Currencies.update_currency(socket.assigns.currency, params, socket.assigns.current_user) do
      {:ok, _currency} ->
        {:noreply,
         socket
         |> put_flash(:info, "Currency updated.")
         |> push_navigate(to: ~p"/admin/currencies")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_currency(socket, :new, params) do
    case Currencies.create_currency(params, socket.assigns.current_user) do
      {:ok, _currency} ->
        {:noreply,
         socket
         |> put_flash(:info, "Currency created.")
         |> push_navigate(to: ~p"/admin/currencies")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl py-12">
      <.header>
        Currencies
        <:actions>
          <.link href={~p"/admin/currencies/export.csv"} class="btn btn-outline">Export CSV</.link>
          <.link
            :if={Policy.can?(@current_user, :create, :currency)}
            href={~p"/admin/currencies/new"}
            class="btn btn-primary"
          >
            New currency
          </.link>
        </:actions>
      </.header>

      <.table id="currencies" rows={@currencies}>
        <:col :let={c} label="Code">{c.code}</:col>
        <:col :let={c} label="Name">{c.name}</:col>
        <:col :let={c} label="Symbol">{c.symbol}</:col>
        <:col :let={c} label="Base?">{c.is_base}</:col>
        <:action :let={c}>
          <.link
            :if={Policy.can?(@current_user, :update, :currency)}
            href={~p"/admin/currencies/#{c.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={c}>
          <.link href={~p"/admin/currencies/#{c.id}/rates"} class="link">Rates</.link>
        </:action>
      </.table>

      <.link href={~p"/"} class="link mt-6 inline-block">&larr; Back</.link>

      <div
        :if={@live_action in [:new, :edit]}
        class="mt-8 max-w-sm rounded-box border border-base-300 p-6"
      >
        <h2 class="text-lg font-semibold">{@page_title}</h2>

        <.form for={@form} id="currency-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:code]} label="Code" />
          <.input field={@form[:name]} label="Name" />
          <.input field={@form[:symbol]} label="Symbol" />
          <.input field={@form[:is_base]} type="checkbox" label="Base currency" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/admin/currencies"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>
      </div>
    </div>
    """
  end
end
