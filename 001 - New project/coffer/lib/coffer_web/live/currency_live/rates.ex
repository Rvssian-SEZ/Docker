defmodule CofferWeb.CurrencyLive.Rates do
  use CofferWeb, :live_view

  alias Coffer.Currencies
  alias Coffer.Currencies.ExchangeRate
  alias Coffer.Authorization.Policy

  @impl true
  def mount(%{"currency_id" => currency_id}, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :exchange_rate) do
      currency = Currencies.get_currency!(currency_id)

      {:ok,
       socket
       |> assign(:currency, currency)
       |> assign(:rates, Currencies.list_exchange_rates(currency.id))
       |> assign(:editing_id, nil)
       |> assign_new_rate_form()}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view exchange rates.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_event("validate", %{"exchange_rate" => params}, socket) do
    changeset =
      case socket.assigns.editing_id && Currencies.get_exchange_rate!(socket.assigns.editing_id) do
        %ExchangeRate{} = rate -> Currencies.change_exchange_rate(rate, params)
        _ -> Currencies.change_exchange_rate(%ExchangeRate{}, params)
      end

    {:noreply, assign(socket, :form, to_form(%{changeset | action: :validate}))}
  end

  def handle_event("save", %{"exchange_rate" => params}, socket) do
    params = Map.put(params, "currency_id", socket.assigns.currency.id)

    case socket.assigns.editing_id do
      nil -> create_rate(socket, params)
      id -> update_rate(socket, id, params)
    end
  end

  def handle_event("edit", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :update, :exchange_rate) do
      rate = Currencies.get_exchange_rate!(id)

      {:noreply,
       socket
       |> assign(:editing_id, rate.id)
       |> assign(:form, to_form(Currencies.change_exchange_rate(rate)))}
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to edit exchange rates.")}
    end
  end

  def handle_event("cancel_edit", _params, socket) do
    {:noreply, socket |> assign(:editing_id, nil) |> assign_new_rate_form()}
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :exchange_rate) do
      rate = Currencies.get_exchange_rate!(id)

      case Currencies.delete_exchange_rate(rate, socket.assigns.current_user) do
        {:ok, _rate} ->
          {:noreply,
           socket
           |> put_flash(:info, "Exchange rate deleted.")
           |> assign(:rates, Currencies.list_exchange_rates(socket.assigns.currency.id))
           |> maybe_clear_editing(id)}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete that rate.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete exchange rates.")}
    end
  end

  defp create_rate(socket, params) do
    if Policy.can?(socket.assigns.current_user, :create, :exchange_rate) do
      case Currencies.create_exchange_rate(params, socket.assigns.current_user) do
        {:ok, _rate} ->
          {:noreply,
           socket
           |> put_flash(:info, "Exchange rate added.")
           |> assign(:rates, Currencies.list_exchange_rates(socket.assigns.currency.id))
           |> assign_new_rate_form()}

        {:error, changeset} ->
          {:noreply, assign(socket, :form, to_form(changeset))}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to add exchange rates.")}
    end
  end

  defp update_rate(socket, id, params) do
    if Policy.can?(socket.assigns.current_user, :update, :exchange_rate) do
      rate = Currencies.get_exchange_rate!(id)

      case Currencies.update_exchange_rate(rate, params, socket.assigns.current_user) do
        {:ok, _rate} ->
          {:noreply,
           socket
           |> put_flash(:info, "Exchange rate updated.")
           |> assign(:rates, Currencies.list_exchange_rates(socket.assigns.currency.id))
           |> assign(:editing_id, nil)
           |> assign_new_rate_form()}

        {:error, changeset} ->
          {:noreply, assign(socket, :form, to_form(changeset))}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to edit exchange rates.")}
    end
  end

  defp assign_new_rate_form(socket) do
    assign(
      socket,
      :form,
      to_form(
        Currencies.change_exchange_rate(%ExchangeRate{}, %{
          "currency_id" => socket.assigns.currency.id
        })
      )
    )
  end

  defp maybe_clear_editing(socket, id) do
    if socket.assigns.editing_id == id do
      socket |> assign(:editing_id, nil) |> assign_new_rate_form()
    else
      socket
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl py-12">
      <.header>Exchange rates — {@currency.code}</.header>

      <.table id="exchange-rates" rows={@rates}>
        <:col :let={r} label="Rate to SCR">{r.rate_to_base}</:col>
        <:col :let={r} label="Effective from">{r.effective_from}</:col>
        <:col :let={r} label="Effective to">{r.effective_to || "current"}</:col>
        <:action :let={r}>
          <button
            :if={Policy.can?(@current_user, :update, :exchange_rate)}
            phx-click="edit"
            phx-value-id={r.id}
            class="link"
          >
            Edit
          </button>
        </:action>
        <:action :let={r}>
          <button
            :if={Policy.can?(@current_user, :delete, :exchange_rate)}
            phx-click="delete"
            phx-value-id={r.id}
            data-confirm="Delete this exchange rate? This does not reopen any other rate period automatically."
            class="link link-error"
          >
            Delete
          </button>
        </:action>
      </.table>

      <.link href={~p"/admin/currencies"} class="link mt-6 inline-block">&larr; Back</.link>

      <div
        :if={
          Policy.can?(@current_user, :create, :exchange_rate) or
            Policy.can?(@current_user, :update, :exchange_rate)
        }
        class="mt-8 max-w-sm rounded-box border border-base-300 p-6"
      >
        <h2 class="text-lg font-semibold">
          {if @editing_id, do: "Edit rate", else: "Add a new rate"}
        </h2>
        <p :if={is_nil(@editing_id)} class="mt-1 text-sm text-base-content/70">
          Any currently open-ended rate for {@currency.code} will be closed the day before this one starts.
        </p>
        <p :if={@editing_id} class="mt-1 text-sm text-base-content/70">
          Editing this row directly corrects it in place — it won't reopen or close any other rate period.
        </p>

        <.form
          for={@form}
          id="exchange-rate-form"
          phx-change="validate"
          phx-submit="save"
          class="mt-4"
        >
          <.input field={@form[:rate_to_base]} type="number" step="0.000001" label="Rate to SCR" />
          <.input field={@form[:effective_from]} type="date" label="Effective from" />
          <.input
            :if={@editing_id}
            field={@form[:effective_to]}
            type="date"
            label="Effective to (blank = open-ended)"
          />
          <footer class="mt-4 flex justify-end gap-2">
            <.link :if={@editing_id} phx-click="cancel_edit" class="btn btn-ghost">
              Cancel
            </.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>
      </div>
    </div>
    """
  end
end
