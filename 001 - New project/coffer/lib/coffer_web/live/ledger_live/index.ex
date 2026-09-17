defmodule CofferWeb.LedgerLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Ledger
  alias Coffer.Ledger.Transaction
  alias Coffer.Currencies
  alias Coffer.Budgets
  alias Coffer.Contracts
  alias Coffer.Vendors
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :ledger_transaction) do
      {:ok,
       socket
       |> assign(:transactions, Ledger.list_transactions())
       |> assign(:currencies, Currencies.list_currencies())
       |> assign(:envelopes, Enum.filter(Budgets.list_envelopes(), & &1.active))
       |> assign(:vendors, Vendors.list_vendors())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view the ledger.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if socket.assigns.live_action in [:new, :edit] and
         not Policy.can?(socket.assigns.current_user, action, :ledger_transaction) do
      {:noreply,
       socket
       |> put_flash(:error, "You're not authorized to do that.")
       |> push_navigate(to: ~p"/ledger")}
    else
      {:noreply, apply_action(socket, socket.assigns.live_action, params)}
    end
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    transaction = Ledger.get_transaction!(id)

    socket
    |> assign(:page_title, "Edit transaction")
    |> assign(:transaction, transaction)
    |> assign(:form, to_form(Ledger.change_transaction(transaction)))
  end

  defp apply_action(socket, :new, params) do
    transaction = prefill_from_contract(params["contract_id"])

    socket
    |> assign(:page_title, "New transaction")
    |> assign(:transaction, transaction)
    |> assign(:form, to_form(Ledger.change_transaction(transaction)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Ledger")
    |> assign(:transaction, nil)
  end

  # "Post this renewal" quick action (from ContractLive) pre-fills a new
  # transaction from the contract instead of building a separate posting
  # flow — the Staff/Admin still reviews and saves it here like any other
  # transaction.
  defp prefill_from_contract(nil), do: %Transaction{}

  defp prefill_from_contract(contract_id) do
    contract = Contracts.get_contract!(contract_id)

    %Transaction{
      date: Date.utc_today(),
      description: "Renewal: #{contract.name}",
      amount: contract.amount,
      currency_id: contract.currency_id,
      direction: :expense,
      budget_envelope_id: contract.budget_envelope_id,
      contract_id: contract.id
    }
  end

  @impl true
  def handle_event("validate", %{"transaction" => params}, socket) do
    form =
      socket.assigns.transaction
      |> Ledger.change_transaction(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"transaction" => params}, socket) do
    action = if socket.assigns.live_action == :new, do: :create, else: :update

    if Policy.can?(socket.assigns.current_user, action, :ledger_transaction) do
      save_transaction(socket, socket.assigns.live_action, params)
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to do that.")}
    end
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :ledger_transaction) do
      transaction = Ledger.get_transaction!(id)

      case Ledger.delete_transaction(transaction, socket.assigns.current_user) do
        {:ok, _transaction} ->
          {:noreply,
           socket
           |> put_flash(:info, "Transaction deleted.")
           |> assign(:transactions, Ledger.list_transactions())}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete transaction.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete transactions.")}
    end
  end

  defp save_transaction(socket, :edit, params) do
    case Ledger.update_transaction(
           socket.assigns.transaction,
           params,
           socket.assigns.current_user
         ) do
      {:ok, _transaction} ->
        {:noreply,
         socket
         |> put_flash(:info, "Transaction updated.")
         |> push_navigate(to: ~p"/ledger")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_transaction(socket, :new, params) do
    case Ledger.create_transaction(params, socket.assigns.current_user) do
      {:ok, _transaction} ->
        {:noreply,
         socket
         |> put_flash(:info, "Transaction created.")
         |> push_navigate(to: ~p"/ledger")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp recurrence_label(%Transaction{recurrence_frequency: freq}) when not is_nil(freq),
    do: Phoenix.Naming.humanize(freq)

  defp recurrence_label(%Transaction{recurrence_source: %Transaction{} = source}),
    do: "↳ from #{source.description}"

  defp recurrence_label(%Transaction{}), do: nil

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-4xl py-12">
      <.header>
        Ledger
        <:actions>
          <.link href={~p"/ledger/export.csv"} class="btn btn-outline">Export CSV</.link>
          <.link href={~p"/ledger/export.xlsx"} class="btn btn-outline">Export XLSX</.link>
          <.link
            :if={Policy.can?(@current_user, :create, :ledger_transaction)}
            href={~p"/ledger/new"}
            class="btn btn-primary"
          >
            New transaction
          </.link>
        </:actions>
      </.header>

      <.table id="ledger-transactions" rows={@transactions}>
        <:col :let={t} label="Date">{t.date}</:col>
        <:col :let={t} label="Description">{t.description}</:col>
        <:col :let={t} label="Direction">{t.direction}</:col>
        <:col :let={t} label="Qty">{t.quantity}</:col>
        <:col :let={t} label="Amount">{format_money(t.amount)} {t.currency.code}</:col>
        <:col :let={t} label="Base amount (SCR)">{format_money(t.amount_base)}</:col>
        <:col :let={t} label="Repeats">{recurrence_label(t)}</:col>
        <:col :let={t} label="Envelope">{t.budget_envelope && t.budget_envelope.name}</:col>
        <:col :let={t} label="Contract">{t.contract && t.contract.name}</:col>
        <:col :let={t} label="Vendor">{t.vendor && t.vendor.name}</:col>
        <:col :let={t} label="Posted by">{t.created_by && t.created_by.name}</:col>
        <:action :let={t}>
          <.link
            :if={Policy.can?(@current_user, :update, :ledger_transaction)}
            href={~p"/ledger/#{t.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={t}>
          <.link
            :if={Policy.can?(@current_user, :delete, :ledger_transaction)}
            phx-click="delete"
            phx-value-id={t.id}
            data-confirm="Delete this transaction?"
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

        <.form for={@form} id="transaction-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:date]} type="date" label="Date" />
          <.input field={@form[:description]} label="Description" />
          <.input
            field={@form[:direction]}
            type="select"
            label="Direction"
            options={
              Enum.map(Coffer.Ledger.Transaction.directions(), &{Phoenix.Naming.humanize(&1), &1})
            }
          />
          <.input field={@form[:amount]} type="number" step="0.01" label="Amount" />
          <.input field={@form[:quantity]} type="number" step="1" label="Quantity (optional)" />
          <.input
            field={@form[:currency_id]}
            type="select"
            label="Currency"
            options={Enum.map(@currencies, &{&1.code, &1.id})}
          />
          <.input
            field={@form[:budget_envelope_id]}
            type="select"
            label="Budget envelope (optional)"
            prompt="None"
            options={Enum.map(@envelopes, &{"#{&1.name} (FY#{&1.fiscal_year})", &1.id})}
          />
          <.input
            field={@form[:vendor_id]}
            type="select"
            label="Vendor (optional)"
            prompt="None"
            options={Enum.map(@vendors, &{&1.name, &1.id})}
          />
          <.input
            field={@form[:recurrence_frequency]}
            type="select"
            label="Repeats"
            prompt="One-off (not recurring)"
            options={
              Enum.map(
                Transaction.recurrence_frequencies(),
                &{Phoenix.Naming.humanize(&1), &1}
              )
            }
          />
          <.input field={@form[:notes]} type="textarea" label="Notes" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/ledger"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>
      </div>
    </div>
    """
  end
end
