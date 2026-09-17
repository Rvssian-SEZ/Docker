defmodule Coffer.Inventory.Checkout do
  use Coffer.Schema
  import Ecto.Changeset

  @statuses [:out, :returned, :overdue, :lost]

  schema "checkouts" do
    field :checked_out_to, :string
    field :checked_out_at, :utc_datetime
    field :due_back_at, :utc_datetime
    field :checked_in_at, :utc_datetime
    field :condition_notes_out, :string
    field :condition_notes_in, :string
    field :status, Ecto.Enum, values: @statuses, default: :out

    belongs_to :inventory_item, Coffer.Inventory.Item
    belongs_to :checked_out_by, Coffer.Accounts.User

    timestamps(type: :utc_datetime)
  end

  def statuses, do: @statuses

  @doc "Used when creating a new checkout — `checked_out_by_id`/`checked_out_at` are set by the context."
  def checkout_changeset(checkout, attrs) do
    checkout
    |> cast(attrs, [:inventory_item_id, :checked_out_to, :due_back_at, :condition_notes_out])
    |> validate_required([:inventory_item_id, :checked_out_to])
    |> foreign_key_constraint(:inventory_item_id)
  end

  @doc "Used exactly once, when the item comes back — sets the final fields, nothing else changes after this."
  def check_in_changeset(checkout, attrs) do
    checkout
    |> cast(attrs, [:condition_notes_in, :status])
    |> validate_required([:status])
    |> validate_inclusion(:status, [:returned, :lost])
  end

  @doc "Used only by `Coffer.Inventory.CheckoutOverdueWorker` to flip `:out` -> `:overdue`."
  def overdue_changeset(checkout) do
    change(checkout, status: :overdue)
  end
end
