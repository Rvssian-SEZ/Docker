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

  @doc """
  Lists items, optionally narrowed by `filters` — a map with any of
  `:search` (matches `name`, case-insensitive substring), `:tracking_type`,
  `:category`, `:location`, `:source`, `:low_stock_only` (boolean-ish —
  truthy string or `true`), and `:page`/`:per_page` (both positive integers
  — omit `:page` for the full unpaginated list, which `count_items/1`,
  CSV export, and the audit log's item-name lookup all still rely on).
  Nil/""/falsy filter values mean "no filter", so params straight off a
  filter form can be passed through unchanged.
  """
  def list_items(filters \\ %{}) do
    filters
    |> filtered_items_query()
    |> order_by(asc: :name)
    |> paginate(filters[:page], filters[:per_page])
    |> preload(:created_by)
    |> Repo.all()
  end

  @doc "Total count matching `filters` (ignores `:page`/`:per_page`) — pairs with `list_items/1` for pagination."
  def count_items(filters \\ %{}), do: filters |> filtered_items_query() |> Repo.aggregate(:count)

  defp filtered_items_query(filters) do
    Item
    |> filter_by(:search, filters[:search])
    |> filter_by(:tracking_type, filters[:tracking_type])
    |> filter_by(:category, filters[:category])
    |> filter_by(:location, filters[:location])
    |> filter_by(:source, filters[:source])
    |> filter_low_stock(filters[:low_stock_only])
  end

  defp paginate(query, page, per_page) when is_integer(page) and page > 0 do
    per_page = per_page || 50
    query |> limit(^per_page) |> offset(^((page - 1) * per_page))
  end

  defp paginate(query, _page, _per_page), do: query

  defp filter_by(query, _field, value) when value in [nil, ""], do: query

  defp filter_by(query, :search, value),
    do: where(query, [i], ilike(i.name, ^"%#{value}%"))

  defp filter_by(query, :tracking_type, value),
    do: where(query, [i], i.tracking_type == ^String.to_existing_atom(value))

  defp filter_by(query, :category, value), do: where(query, [i], i.category == ^value)
  defp filter_by(query, :location, value), do: where(query, [i], i.location == ^value)

  defp filter_by(query, :source, value),
    do: where(query, [i], i.source == ^String.to_existing_atom(value))

  defp filter_low_stock(query, value) when value in [true, "true"] do
    where(
      query,
      [i],
      i.tracking_type == :consumable and not is_nil(i.reorder_threshold) and
        i.quantity_on_hand <= i.reorder_threshold
    )
  end

  defp filter_low_stock(query, _value), do: query

  @doc "Distinct, non-empty category values in use, for a filter dropdown."
  def distinct_categories do
    Item
    |> where([i], not is_nil(i.category) and i.category != "")
    |> distinct(true)
    |> select([i], i.category)
    |> order_by([i], i.category)
    |> Repo.all()
  end

  @doc "Distinct, non-empty location values in use, for a filter dropdown."
  def distinct_locations do
    Item
    |> where([i], not is_nil(i.location) and i.location != "")
    |> distinct(true)
    |> select([i], i.location)
    |> order_by([i], i.location)
    |> Repo.all()
  end

  @doc "Whether any item currently comes from Snipe-IT — drives the edit-gets-overwritten warning banner."
  def any_snipeit_items?, do: Repo.exists?(where(Item, source: :snipeit))

  def get_item!(id), do: Repo.get!(Item, id) |> Repo.preload(:created_by)

  def get_item_by_external_id(external_id), do: Repo.get_by(Item, external_id: external_id)

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

  @doc "Only used by `Coffer.SnipeIt` — creates a new item sourced from Snipe-IT."
  def sync_create_item(attrs, %User{} = actor) do
    changeset =
      %Item{}
      |> Item.snipeit_create_changeset(attrs)
      |> Ecto.Changeset.put_change(:created_by_id, actor.id)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:item, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{item: i} ->
      AuditLog.record(actor.id, :create, "InventoryItem", i.id, %{after: serialize_item(i)})
    end)
    |> Repo.transaction()
    |> unwrap(:item)
  end

  @doc """
  Only used by `Coffer.SnipeIt` — updates the non-quantity fields of an
  already-synced item. Skips the audit-log write entirely when nothing
  actually changed, so a routine re-sync of thousands of untouched Snipe-IT
  rows doesn't flood the audit log with no-op entries.
  """
  def sync_update_item(%Item{} = item, attrs, %User{} = actor) do
    before = serialize_item(item)
    changeset = Item.snipeit_update_changeset(item, attrs)
    meaningful_changes = Map.delete(changeset.changes, :external_updated_at)

    if meaningful_changes == %{} do
      # Still persist a bumped external_updated_at (if any) so the next
      # sync's diff is against current data, but nothing worth an audit
      # entry actually changed — skip it rather than logging a no-op.
      Repo.update(changeset)
    else
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
      active: i.active,
      source: i.source,
      external_id: i.external_id,
      assigned_to: i.assigned_to
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
