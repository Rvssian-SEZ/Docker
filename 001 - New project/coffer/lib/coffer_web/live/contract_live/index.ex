defmodule CofferWeb.ContractLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Contracts
  alias Coffer.Contracts.Contract
  alias Coffer.Vendors
  alias Coffer.Currencies
  alias Coffer.Budgets
  alias Coffer.Attachments
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :contract) do
      {:ok,
       socket
       |> assign(:contracts, Contracts.list_contracts())
       |> assign(:vendors, Vendors.list_vendors())
       |> assign(:currencies, Currencies.list_currencies())
       |> assign(:envelopes, Enum.filter(Budgets.list_envelopes(), & &1.active))
       |> allow_upload(:attachment,
         accept: Attachments.allowed_content_types(),
         max_entries: 1,
         max_file_size: Attachments.max_bytes()
       )}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view contracts.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    {:noreply, apply_action(socket, socket.assigns.live_action, params)}
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    contract = Contracts.get_contract!(id)

    socket
    |> assign(:page_title, "Edit contract")
    |> assign(:contract, contract)
    |> assign(:form, to_form(Contracts.change_contract(contract)))
  end

  defp apply_action(socket, :new, _params) do
    contract = %Contract{}

    socket
    |> assign(:page_title, "New contract")
    |> assign(:contract, contract)
    |> assign(:form, to_form(Contracts.change_contract(contract)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Contracts")
    |> assign(:contract, nil)
  end

  @impl true
  def handle_event("validate", %{"contract" => params}, socket) do
    form =
      socket.assigns.contract
      |> Contracts.change_contract(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"contract" => params}, socket) do
    save_contract(socket, socket.assigns.live_action, params)
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :contract) do
      contract = Contracts.get_contract!(id)

      case Contracts.delete_contract(contract, socket.assigns.current_user) do
        {:ok, _contract} ->
          {:noreply,
           socket
           |> put_flash(:info, "Contract deleted.")
           |> assign(:contracts, Contracts.list_contracts())}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete contract.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete contracts.")}
    end
  end

  # Required so the upload form's file-input change events (progress
  # tracking) have a handler — the actual upload happens on submit.
  def handle_event("noop", _params, socket), do: {:noreply, socket}

  def handle_event("upload_attachment", _params, socket) do
    if Policy.can?(socket.assigns.current_user, :update, :contract) do
      contract = socket.assigns.contract

      uploaded =
        consume_uploaded_entries(socket, :attachment, fn %{path: path}, entry ->
          upload = %Plug.Upload{
            path: path,
            filename: entry.client_name,
            content_type: entry.client_type
          }

          case Contracts.add_attachment(contract, upload, socket.assigns.current_user) do
            {:ok, _attachment} -> {:ok, :ok}
            {:error, changeset} -> {:postpone, changeset}
          end
        end)

      if Enum.all?(uploaded, &(&1 == :ok)) and uploaded != [] do
        {:noreply,
         socket
         |> put_flash(:info, "Attachment uploaded.")
         |> assign(:contract, Contracts.get_contract!(contract.id))}
      else
        {:noreply, put_flash(socket, :error, "Could not upload that file.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to add attachments.")}
    end
  end

  def handle_event("delete_attachment", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :update, :contract) do
      attachment = Enum.find(socket.assigns.contract.attachments, &(&1.id == id))

      case attachment && Contracts.delete_attachment(attachment, socket.assigns.current_user) do
        {:ok, _} ->
          {:noreply,
           socket
           |> put_flash(:info, "Attachment removed.")
           |> assign(:contract, Contracts.get_contract!(socket.assigns.contract.id))}

        _ ->
          {:noreply, put_flash(socket, :error, "Could not remove that attachment.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to remove attachments.")}
    end
  end

  defp save_contract(socket, :edit, params) do
    case Contracts.update_contract(socket.assigns.contract, params, socket.assigns.current_user) do
      {:ok, _contract} ->
        {:noreply,
         socket
         |> put_flash(:info, "Contract updated.")
         |> push_navigate(to: ~p"/contracts")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_contract(socket, :new, params) do
    case Contracts.create_contract(params, socket.assigns.current_user) do
      {:ok, _contract} ->
        {:noreply,
         socket
         |> put_flash(:info, "Contract created.")
         |> push_navigate(to: ~p"/contracts")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-4xl py-12">
      <.header>
        Contracts
        <:actions>
          <.link href={~p"/contracts/export.csv"} class="btn btn-outline">Export CSV</.link>
          <.link
            :if={Policy.can?(@current_user, :create, :contract)}
            href={~p"/contracts/new"}
            class="btn btn-primary"
          >
            New contract
          </.link>
        </:actions>
      </.header>

      <.table id="contracts" rows={@contracts}>
        <:col :let={c} label="Name">{c.name}</:col>
        <:col :let={c} label="Vendor">{c.vendor.name}</:col>
        <:col :let={c} label="Type">{c.contract_type}</:col>
        <:col :let={c} label="Renewal date">{c.renewal_date}</:col>
        <:col :let={c} label="Amount">{c.amount} {c.currency.code}</:col>
        <:col :let={c} label="Auto-post?">{c.auto_post_to_ledger}</:col>
        <:col :let={c} label="Status">{c.status}</:col>
        <:action :let={c}>
          <.link
            :if={
              Policy.can?(@current_user, :create, :ledger_transaction) and not c.auto_post_to_ledger and
                not is_nil(c.renewal_date)
            }
            href={~p"/ledger/new?contract_id=#{c.id}"}
            class="link"
          >
            Post this renewal
          </.link>
        </:action>
        <:action :let={c}>
          <.link
            :if={Policy.can?(@current_user, :update, :contract)}
            href={~p"/contracts/#{c.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={c}>
          <.link
            :if={Policy.can?(@current_user, :delete, :contract)}
            phx-click="delete"
            phx-value-id={c.id}
            data-confirm="Delete this contract?"
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

        <.form for={@form} id="contract-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:name]} label="Name" />
          <.input
            field={@form[:vendor_id]}
            type="select"
            label="Vendor"
            prompt="Choose a vendor"
            options={Enum.map(@vendors, &{&1.name, &1.id})}
          />
          <.input
            field={@form[:contract_type]}
            type="select"
            label="Contract type"
            options={Enum.map(Contract.contract_types(), &{Phoenix.Naming.humanize(&1), &1})}
          />
          <.input field={@form[:start_date]} type="date" label="Start date" />
          <.input field={@form[:end_date]} type="date" label="End date (optional)" />
          <.input field={@form[:renewal_date]} type="date" label="Renewal date (optional)" />
          <.input
            field={@form[:renewal_frequency]}
            type="select"
            label="Renewal frequency (optional)"
            prompt="None"
            options={Enum.map(Contract.renewal_frequencies(), &{Phoenix.Naming.humanize(&1), &1})}
          />
          <.input field={@form[:amount]} type="number" step="0.01" label="Amount" />
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
            field={@form[:auto_post_to_ledger]}
            type="checkbox"
            label="Auto-post to ledger on renewal"
          />
          <.input
            field={@form[:status]}
            type="select"
            label="Status"
            options={Enum.map(Contract.statuses(), &{Phoenix.Naming.humanize(&1), &1})}
          />
          <.input field={@form[:notes]} type="textarea" label="Notes" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/contracts"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>

        <div :if={@live_action == :edit} class="mt-8 border-t border-base-300 pt-6">
          <h3 class="font-semibold">Attachments</h3>

          <ul class="mt-2 space-y-1">
            <li :for={a <- @contract.attachments} class="flex items-center justify-between">
              <span>{a.original_filename}</span>
              <button
                :if={Policy.can?(@current_user, :update, :contract)}
                phx-click="delete_attachment"
                phx-value-id={a.id}
                data-confirm={"Remove \"#{a.original_filename}\"?"}
                class="link link-error text-sm"
              >
                Remove
              </button>
            </li>
          </ul>

          <form
            :if={Policy.can?(@current_user, :update, :contract)}
            phx-submit="upload_attachment"
            phx-change="noop"
            class="mt-4"
          >
            <.live_file_input upload={@uploads.attachment} />
            <div :for={err <- upload_errors(@uploads.attachment)} class="text-error text-sm mt-1">
              {Phoenix.Naming.humanize(err)}
            </div>
            <.button phx-disable-with="Uploading...">Upload</.button>
          </form>
        </div>
      </div>
    </div>
    """
  end
end
