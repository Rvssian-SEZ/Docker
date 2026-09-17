defmodule CofferWeb.InventoryLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Inventory
  alias Coffer.Inventory.Item
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :inventory_item) do
      {:ok, assign(socket, :items, Inventory.list_items())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view inventory.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def handle_params(params, _url, socket) do
    {:noreply, apply_action(socket, socket.assigns.live_action, params)}
  end

  defp apply_action(socket, :edit, %{"id" => id}) do
    item = Inventory.get_item!(id)

    socket
    |> assign(:page_title, "Edit item")
    |> assign(:item, item)
    |> assign(:form, to_form(Inventory.change_item(item)))
    |> assign(:transactions, Inventory.list_transactions_for_item(item))
    |> assign(:checkouts, Inventory.list_checkouts_for_item(item))
    |> assign(:stock_form, to_form(%{}, as: :stock))
    |> assign(:checkout_form, to_form(%{}, as: :checkout))
    |> assign(:checkin_id, nil)
    |> assign(:checkin_form, to_form(%{}, as: :checkin))
  end

  defp apply_action(socket, :new, _params) do
    item = %Item{}

    socket
    |> assign(:page_title, "New item")
    |> assign(:item, item)
    |> assign(:form, to_form(Inventory.change_new_item(item)))
  end

  defp apply_action(socket, :index, _params) do
    socket
    |> assign(:page_title, "Inventory")
    |> assign(:item, nil)
  end

  @impl true
  def handle_event("validate", %{"item" => params}, socket) do
    change_fn =
      if socket.assigns.live_action == :new,
        do: &Inventory.change_new_item/2,
        else: &Inventory.change_item/2

    form =
      socket.assigns.item
      |> change_fn.(params)
      |> Map.put(:action, :validate)
      |> to_form()

    {:noreply, assign(socket, :form, form)}
  end

  def handle_event("save", %{"item" => params}, socket) do
    save_item(socket, socket.assigns.live_action, params)
  end

  def handle_event("delete", %{"id" => id}, socket) do
    if Policy.can?(socket.assigns.current_user, :delete, :inventory_item) do
      item = Inventory.get_item!(id)

      case Inventory.delete_item(item, socket.assigns.current_user) do
        {:ok, _item} ->
          {:noreply,
           socket
           |> put_flash(:info, "Item deleted.")
           |> assign(:items, Inventory.list_items())}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not delete item.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to delete inventory items.")}
    end
  end

  def handle_event("stock_move", %{"stock" => %{"type" => type} = params}, socket) do
    if Policy.can?(socket.assigns.current_user, :create, :inventory_transaction) do
      item = socket.assigns.item

      attrs = %{
        "quantity" => params["quantity"],
        "date" => params["date"],
        "notes" => params["notes"]
      }

      attrs =
        if type == "issue", do: Map.put(attrs, "issued_to", params["issued_to"]), else: attrs

      result =
        case type do
          "issue" -> Inventory.issue_stock(item, attrs, socket.assigns.current_user)
          "receive" -> Inventory.receive_stock(item, attrs, socket.assigns.current_user)
          "adjustment" -> Inventory.adjust_stock(item, attrs, socket.assigns.current_user)
        end

      case result do
        {:ok, _txn} ->
          item = Inventory.get_item!(item.id)

          {:noreply,
           socket
           |> put_flash(:info, "Stock updated.")
           |> assign(:item, item)
           |> assign(:transactions, Inventory.list_transactions_for_item(item))
           |> assign(:stock_form, to_form(%{}, as: :stock))}

        {:error, changeset} ->
          {:noreply,
           put_flash(socket, :error, "Could not record that: #{error_summary(changeset)}")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to move stock.")}
    end
  end

  def handle_event("checkout", %{"checkout" => params}, socket) do
    if Policy.can?(socket.assigns.current_user, :create, :checkout) do
      item = socket.assigns.item

      due_back_at =
        case params["due_back_at"] do
          "" -> nil
          date_str -> date_str <> "T00:00:00Z"
        end

      attrs = %{
        "checked_out_to" => params["checked_out_to"],
        "due_back_at" => due_back_at,
        "condition_notes_out" => params["condition_notes_out"]
      }

      case Inventory.checkout_item(item, attrs, socket.assigns.current_user) do
        {:ok, _checkout} ->
          item = Inventory.get_item!(item.id)

          {:noreply,
           socket
           |> put_flash(:info, "Checked out.")
           |> assign(:item, item)
           |> assign(:checkouts, Inventory.list_checkouts_for_item(item))
           |> assign(:checkout_form, to_form(%{}, as: :checkout))}

        {:error, :none_available} ->
          {:noreply, put_flash(socket, :error, "No units currently available.")}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not check out that item.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to check out items.")}
    end
  end

  def handle_event("start_check_in", %{"id" => id}, socket) do
    {:noreply, assign(socket, :checkin_id, id)}
  end

  def handle_event("cancel_check_in", _params, socket) do
    {:noreply, assign(socket, :checkin_id, nil)}
  end

  def handle_event("check_in", %{"checkin" => params}, socket) do
    if Policy.can?(socket.assigns.current_user, :update, :checkout) do
      checkout = Inventory.get_checkout!(socket.assigns.checkin_id)

      attrs = %{
        "condition_notes_in" => params["condition_notes_in"],
        "status" => params["status"]
      }

      case Inventory.check_in_item(checkout, attrs, socket.assigns.current_user) do
        {:ok, _checkout} ->
          item = Inventory.get_item!(socket.assigns.item.id)

          {:noreply,
           socket
           |> put_flash(:info, "Checked in.")
           |> assign(:item, item)
           |> assign(:checkouts, Inventory.list_checkouts_for_item(item))
           |> assign(:checkin_id, nil)}

        {:error, _changeset} ->
          {:noreply, put_flash(socket, :error, "Could not check in that item.")}
      end
    else
      {:noreply, put_flash(socket, :error, "You're not authorized to check in items.")}
    end
  end

  defp save_item(socket, :edit, params) do
    case Inventory.update_item(socket.assigns.item, params, socket.assigns.current_user) do
      {:ok, _item} ->
        {:noreply,
         socket
         |> put_flash(:info, "Item updated.")
         |> push_navigate(to: ~p"/inventory")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp save_item(socket, :new, params) do
    case Inventory.create_item(params, socket.assigns.current_user) do
      {:ok, _item} ->
        {:noreply,
         socket
         |> put_flash(:info, "Item created.")
         |> push_navigate(to: ~p"/inventory")}

      {:error, changeset} ->
        {:noreply, assign(socket, :form, to_form(changeset))}
    end
  end

  defp error_summary(changeset) do
    changeset
    |> Ecto.Changeset.traverse_errors(fn {msg, _opts} -> msg end)
    |> Enum.map_join(", ", fn {field, errs} -> "#{field} #{Enum.join(errs, ", ")}" end)
  end

  defp low_stock?(%Item{tracking_type: :consumable, reorder_threshold: t, quantity_on_hand: q})
       when not is_nil(t),
       do: q <= t

  defp low_stock?(_item), do: false

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-4xl py-12">
      <.header>
        Inventory
        <:actions>
          <.link href={~p"/inventory/export.csv"} class="btn btn-outline">Export CSV</.link>
          <.link href={~p"/inventory/checkouts/export.csv"} class="btn btn-outline">
            Export checkouts CSV
          </.link>
          <.link
            :if={Policy.can?(@current_user, :create, :inventory_item)}
            href={~p"/inventory/new"}
            class="btn btn-primary"
          >
            New item
          </.link>
        </:actions>
      </.header>

      <.table id="inventory-items" rows={@items}>
        <:col :let={i} label="Name">
          {i.name}
          <span :if={low_stock?(i)} class="badge badge-error badge-sm ml-2">low stock</span>
        </:col>
        <:col :let={i} label="Type">{i.tracking_type}</:col>
        <:col :let={i} label="Category">{i.category}</:col>
        <:col :let={i} label="On hand">{i.quantity_on_hand}</:col>
        <:col :let={i} label="Available">
          {if i.tracking_type == :checkoutable, do: Inventory.available(i), else: "—"}
        </:col>
        <:col :let={i} label="Location">{i.location}</:col>
        <:action :let={i}>
          <.link
            :if={Policy.can?(@current_user, :update, :inventory_item)}
            href={~p"/inventory/#{i.id}/edit"}
            class="link"
          >
            Edit
          </.link>
        </:action>
        <:action :let={i}>
          <.link
            :if={Policy.can?(@current_user, :delete, :inventory_item)}
            phx-click="delete"
            phx-value-id={i.id}
            data-confirm="Delete this item? This does not delete its transaction/checkout history."
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

        <.form for={@form} id="item-form" phx-change="validate" phx-submit="save" class="mt-4">
          <.input field={@form[:name]} label="Name" />
          <.input field={@form[:description]} type="textarea" label="Description" />
          <.input
            field={@form[:tracking_type]}
            type="select"
            label="Tracking type"
            options={Enum.map(Item.tracking_types(), &{Phoenix.Naming.humanize(&1), &1})}
          />
          <.input field={@form[:category]} label="Category" />
          <.input
            :if={@live_action == :new}
            field={@form[:quantity_on_hand]}
            type="number"
            step="1"
            label="Starting quantity on hand"
          />
          <.input
            field={@form[:reorder_threshold]}
            type="number"
            step="1"
            label="Reorder threshold (consumables only)"
          />
          <.input field={@form[:unit_cost]} type="number" step="0.01" label="Unit cost (optional)" />
          <.input field={@form[:location]} label="Location" />
          <.input field={@form[:active]} type="checkbox" label="Active" />
          <footer class="mt-4 flex justify-end gap-2">
            <.link href={~p"/inventory"} class="btn btn-ghost">Cancel</.link>
            <.button phx-disable-with="Saving...">Save</.button>
          </footer>
        </.form>

        <div
          :if={@live_action == :edit and @item.tracking_type == :consumable}
          class="mt-8 border-t border-base-300 pt-6"
        >
          <h3 class="font-semibold">Move stock</h3>

          <.form for={@stock_form} id="stock-form" phx-submit="stock_move" class="mt-4">
            <.input
              type="select"
              name="stock[type]"
              label="Type"
              options={[
                {"Issue", "issue"},
                {"Receive", "receive"},
                {"Adjustment (add)", "adjustment"}
              ]}
            />
            <.input type="number" name="stock[quantity]" label="Quantity" />
            <.input type="date" name="stock[date]" label="Date" />
            <.input type="text" name="stock[issued_to]" label="Issued to (issue only)" />
            <.input type="text" name="stock[notes]" label="Notes" />
            <footer class="mt-4 flex justify-end">
              <.button phx-disable-with="Saving...">Record</.button>
            </footer>
          </.form>

          <h4 class="mt-6 text-sm font-semibold">History</h4>
          <.table id="inventory-transactions" rows={@transactions}>
            <:col :let={t} label="Date">{t.date}</:col>
            <:col :let={t} label="Type">{t.transaction_type}</:col>
            <:col :let={t} label="Qty">{t.quantity}</:col>
            <:col :let={t} label="Issued to">{t.issued_to}</:col>
            <:col :let={t} label="Notes">{t.notes}</:col>
          </.table>
        </div>

        <div
          :if={@live_action == :edit and @item.tracking_type == :checkoutable}
          class="mt-8 border-t border-base-300 pt-6"
        >
          <h3 class="font-semibold">Checkouts</h3>

          <.form for={@checkout_form} id="checkout-form" phx-submit="checkout" class="mt-4">
            <.input type="text" name="checkout[checked_out_to]" label="Checked out to" />
            <.input type="date" name="checkout[due_back_at]" label="Due back (optional)" />
            <.input
              type="text"
              name="checkout[condition_notes_out]"
              label="Condition notes (optional)"
            />
            <footer class="mt-4 flex justify-end">
              <.button phx-disable-with="Saving...">Check out</.button>
            </footer>
          </.form>

          <h4 class="mt-6 text-sm font-semibold">History</h4>
          <.table id="checkouts" rows={@checkouts}>
            <:col :let={c} label="To">{c.checked_out_to}</:col>
            <:col :let={c} label="Out">{c.checked_out_at}</:col>
            <:col :let={c} label="Due">{c.due_back_at}</:col>
            <:col :let={c} label="Status">{c.status}</:col>
            <:action :let={c}>
              <button
                :if={c.status in [:out, :overdue] and Policy.can?(@current_user, :update, :checkout)}
                phx-click="start_check_in"
                phx-value-id={c.id}
                class="link"
              >
                Check in
              </button>
            </:action>
          </.table>

          <div :if={@checkin_id} class="mt-4 rounded-box border border-base-300 p-4">
            <.form for={@checkin_form} id="checkin-form" phx-submit="check_in">
              <.input
                type="text"
                name="checkin[condition_notes_in]"
                label="Condition notes (optional)"
              />
              <.input
                type="select"
                name="checkin[status]"
                label="Status"
                options={[{"Returned", "returned"}, {"Lost", "lost"}]}
              />
              <footer class="mt-4 flex justify-end gap-2">
                <.link phx-click="cancel_check_in" class="btn btn-ghost">Cancel</.link>
                <.button phx-disable-with="Saving...">Confirm check-in</.button>
              </footer>
            </.form>
          </div>
        </div>
      </div>
    </div>
    """
  end
end
