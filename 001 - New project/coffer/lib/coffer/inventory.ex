defmodule Coffer.Inventory do
  @moduledoc """
  Consumable/asset tracking (spec §4.7) — a single `inventory_items` table
  with a dual lifecycle: `quantity_on_hand` is a live stock count for
  `:consumable` items (moved by issue/receive/adjustment events) and a total
  owned count for `:checkoutable` items (moved in/out via `checkouts` rows,
  "available" always computed at query time, never stored — same pattern as
  budget envelope `remaining`, spec §4.3/§4.7).
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Notifications
  alias Coffer.Accounts.User
  alias Coffer.Inventory.{Item, Transaction, Checkout}

  # --- Items --------------------------------------------------------

  def list_items do
    Item
    |> order_by(asc: :name)
    |> preload(:created_by)
    |> Repo.all()
  end

  def get_item!(id), do: Repo.get!(Item, id) |> Repo.preload(:created_by)

  def change_item(%Item{} = item, attrs \\ %{}), do: Item.changeset(item, attrs)

  def change_new_item(%Item{} = item, attrs \\ %{}), do: Item.create_changeset(item, attrs)

  def create_item(attrs, %User{} = actor) do
    changeset =
      %Item{}
      |> Item.create_changeset(attrs)
      |> Ecto.Changeset.put_change(:created_by_id, actor.id)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:item, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{item: i} ->
      AuditLog.record(actor.id, :create, "InventoryItem", i.id, %{after: serialize_item(i)})
    end)
    |> Repo.transaction()
    |> unwrap(:item)
  end

  def update_item(%Item{} = item, attrs, %User{} = actor) do
    before = serialize_item(item)
    changeset = Item.changeset(item, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:item, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{item: i} ->
      AuditLog.record(actor.id, :update, "InventoryItem", i.id, %{
        before: before,
        after: serialize_item(i)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:item)
  end

  def delete_item(%Item{} = item, %User{} = actor) do
    before = serialize_item(item)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:item, item)
    |> Ecto.Multi.run(:audit, fn _repo, %{item: i} ->
      AuditLog.record(actor.id, :delete, "InventoryItem", i.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap(:item)
  end

  @doc "For `:checkoutable` items — total owned minus units currently out. Never stored."
  def available(%Item{} = item) do
    item.quantity_on_hand - currently_out_count(item)
  end

  defp currently_out_count(%Item{} = item) do
    Checkout
    |> where(inventory_item_id: ^item.id, status: :out)
    |> select([c], count(c.id))
    |> Repo.one()
  end

  # --- Consumable stock movements -------------------------------------

  def list_transactions_for_item(%Item{} = item) do
    Transaction
    |> where(inventory_item_id: ^item.id)
    |> order_by(desc: :date, desc: :inserted_at)
    |> preload(:created_by)
    |> Repo.all()
  end

  def issue_stock(%Item{} = item, attrs, %User{} = actor),
    do: apply_stock_change(item, :issue, -1, attrs, actor)

  def receive_stock(%Item{} = item, attrs, %User{} = actor),
    do: apply_stock_change(item, :receive, 1, attrs, actor)

  def adjust_stock(%Item{} = item, attrs, %User{} = actor),
    do: apply_stock_change(item, :adjustment, 1, attrs, actor)

  defp apply_stock_change(item, transaction_type, sign, attrs, %User{} = actor) do
    txn_changeset =
      %Transaction{}
      |> Transaction.changeset(
        attrs
        |> Map.new(fn {k, v} -> {to_string(k), v} end)
        |> Map.put("inventory_item_id", item.id)
        |> Map.put("transaction_type", Atom.to_string(transaction_type))
      )
      |> Ecto.Changeset.put_change(:created_by_id, actor.id)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:transaction, txn_changeset)
    |> Ecto.Multi.run(:item, fn _repo, %{transaction: txn} ->
      item
      |> Item.quantity_changeset(item.quantity_on_hand + sign * txn.quantity)
      |> Repo.update()
    end)
    |> Ecto.Multi.run(:audit, fn _repo, %{transaction: txn} ->
      AuditLog.record(actor.id, :create, "InventoryTransaction", txn.id, %{
        after: serialize_transaction(txn)
      })
    end)
    |> Repo.transaction()
    |> case do
      {:ok, %{transaction: txn, item: updated_item}} ->
        maybe_notify_low_stock(item, updated_item)
        {:ok, txn}

      {:error, :transaction, changeset, _changes} ->
        {:error, changeset}

      {:error, :item, changeset, _changes} ->
        {:error, changeset}
    end
  end

  defp maybe_notify_low_stock(%Item{} = before_item, %Item{} = after_item) do
    threshold = after_item.reorder_threshold

    if (threshold && before_item.quantity_on_hand > threshold) and
         after_item.quantity_on_hand <= threshold do
      Notifications.create(%{
        user_id: nil,
        type: :low_stock,
        message:
          "#{after_item.name} is at or below its reorder threshold (#{after_item.quantity_on_hand} on hand, threshold #{threshold}).",
        link: "/inventory/#{after_item.id}/edit"
      })
    end
  end

  # --- Checkouts -------------------------------------------------------

  def get_checkout!(id), do: Repo.get!(Checkout, id) |> Repo.preload([:inventory_item])

  def list_checkouts_for_item(%Item{} = item) do
    Checkout
    |> where(inventory_item_id: ^item.id)
    |> order_by(desc: :checked_out_at)
    |> preload(:checked_out_by)
    |> Repo.all()
  end

  @doc "The worker's own working set — every checkout not yet checked back in."
  def list_open_checkouts do
    Checkout
    |> where([c], is_nil(c.checked_in_at))
    |> preload(:inventory_item)
    |> Repo.all()
  end

  @doc "Every checkout across every item, most recent first — backs the checkouts export."
  def list_all_checkouts do
    Checkout
    |> order_by(desc: :checked_out_at)
    |> preload([:inventory_item, :checked_out_by])
    |> Repo.all()
  end

  def checkout_item(%Item{} = item, attrs, %User{} = actor) do
    if available(item) > 0 do
      now = DateTime.utc_now() |> DateTime.truncate(:second)

      changeset =
        %Checkout{}
        |> Checkout.checkout_changeset(
          attrs
          |> Map.new(fn {k, v} -> {to_string(k), v} end)
          |> Map.put("inventory_item_id", item.id)
        )
        |> Ecto.Changeset.put_change(:checked_out_by_id, actor.id)
        |> Ecto.Changeset.put_change(:checked_out_at, now)

      Ecto.Multi.new()
      |> Ecto.Multi.insert(:checkout, changeset)
      |> Ecto.Multi.run(:audit, fn _repo, %{checkout: c} ->
        AuditLog.record(actor.id, :create, "Checkout", c.id, %{after: serialize_checkout(c)})
      end)
      |> Repo.transaction()
      |> unwrap(:checkout)
    else
      {:error, :none_available}
    end
  end

  def check_in_item(%Checkout{} = checkout, attrs, %User{} = actor) do
    before = serialize_checkout(checkout)
    now = DateTime.utc_now() |> DateTime.truncate(:second)

    changeset =
      checkout
      |> Checkout.check_in_changeset(attrs)
      |> Ecto.Changeset.put_change(:checked_in_at, now)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:checkout, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{checkout: c} ->
      AuditLog.record(actor.id, :update, "Checkout", c.id, %{
        before: before,
        after: serialize_checkout(c)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:checkout)
  end

  @doc "System-triggered `:out` -> `:overdue` flip — used only by `CheckoutOverdueWorker`, no authenticated actor."
  def system_mark_overdue(%Checkout{} = checkout) do
    before = serialize_checkout(checkout)
    changeset = Checkout.overdue_changeset(checkout)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:checkout, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{checkout: c} ->
      AuditLog.record(nil, :update, "Checkout", c.id, %{
        before: before,
        after: serialize_checkout(c)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:checkout)
  end

  defp serialize_item(%Item{} = i) do
    %{
      id: i.id,
      name: i.name,
      tracking_type: i.tracking_type,
      category: i.category,
      quantity_on_hand: i.quantity_on_hand,
      reorder_threshold: i.reorder_threshold,
      unit_cost: i.unit_cost && Decimal.to_string(i.unit_cost),
      location: i.location,
      active: i.active
    }
  end

  defp serialize_transaction(%Transaction{} = t) do
    %{
      id: t.id,
      inventory_item_id: t.inventory_item_id,
      transaction_type: t.transaction_type,
      quantity: t.quantity,
      issued_to: t.issued_to,
      date: t.date,
      notes: t.notes
    }
  end

  defp serialize_checkout(%Checkout{} = c) do
    %{
      id: c.id,
      inventory_item_id: c.inventory_item_id,
      checked_out_to: c.checked_out_to,
      checked_out_at: c.checked_out_at,
      due_back_at: c.due_back_at,
      checked_in_at: c.checked_in_at,
      status: c.status
    }
  end

  defp unwrap({:ok, %{item: result}}, :item), do: {:ok, result}
  defp unwrap({:ok, %{checkout: result}}, :checkout), do: {:ok, result}
  defp unwrap({:error, _failed_op, changeset, _changes}, _key), do: {:error, changeset}
end
