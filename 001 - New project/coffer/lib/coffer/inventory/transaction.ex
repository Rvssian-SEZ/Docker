defmodule Coffer.Inventory.Transaction do
  use Coffer.Schema
  import Ecto.Changeset

  @transaction_types [:issue, :receive, :adjustment]

  schema "inventory_transactions" do
    field :transaction_type, Ecto.Enum, values: @transaction_types
    field :quantity, :integer
    field :issued_to, :string
    field :date, :date
    field :notes, :string

    belongs_to :inventory_item, Coffer.Inventory.Item
    belongs_to :created_by, Coffer.Accounts.User

    timestamps(type: :utc_datetime)
  end

  def transaction_types, do: @transaction_types

  @doc """
  Append-only event log — spec gives ledger transactions explicit
  direct-edit/delete rights (§4.4) but says nothing like that here, and a
  stock ledger reads more naturally as a sequence of discrete events than
  something you revise after the fact, so there's no update/delete path in
  `Coffer.Inventory` for these rows (flagged in case the user wants ledger
  parity instead).

  `quantity` is always a positive count regardless of `transaction_type` —
  spec §4.7 literally says on-hand "decrements on issue, increments on
  receive/adjustment (positive)", so `adjustment` here means "add stock
  found/corrected upward," not a general positive-or-negative correction.
  """
  def changeset(transaction, attrs) do
    transaction
    |> cast(attrs, [:inventory_item_id, :transaction_type, :quantity, :issued_to, :date, :notes])
    |> validate_required([:inventory_item_id, :transaction_type, :quantity, :date])
    |> validate_number(:quantity, greater_than: 0)
    |> foreign_key_constraint(:inventory_item_id)
  end
end
