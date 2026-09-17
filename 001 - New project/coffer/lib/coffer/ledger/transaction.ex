defmodule Coffer.Ledger.Transaction do
  use Coffer.Schema
  import Ecto.Changeset

  @directions [:income, :expense]

  schema "ledger_transactions" do
    field :date, :date
    field :description, :string
    field :amount, :decimal
    field :amount_base, :decimal
    field :direction, Ecto.Enum, values: @directions
    field :quantity, :integer
    field :notes, :string

    belongs_to :currency, Coffer.Currencies.Currency
    belongs_to :created_by, Coffer.Accounts.User
    belongs_to :budget_envelope, Coffer.Budgets.Envelope
    belongs_to :contract, Coffer.Contracts.Contract
    belongs_to :vendor, Coffer.Vendors.Vendor

    timestamps(type: :utc_datetime)
  end

  def directions, do: @directions

  @doc """
  User-facing fields only — `amount_base` and `created_by_id` are set by
  `Coffer.Ledger` from the authenticated actor and the date-effective
  exchange rate, never taken directly from form/API input.
  """
  def changeset(transaction, attrs) do
    transaction
    |> cast(attrs, [
      :date,
      :description,
      :amount,
      :currency_id,
      :direction,
      :quantity,
      :budget_envelope_id,
      :contract_id,
      :vendor_id,
      :notes
    ])
    |> validate_required([:date, :description, :amount, :currency_id, :direction])
    |> validate_number(:amount, greater_than: 0)
    |> validate_number(:quantity, greater_than: 0)
    |> foreign_key_constraint(:currency_id)
    |> foreign_key_constraint(:budget_envelope_id)
    |> foreign_key_constraint(:contract_id)
    |> foreign_key_constraint(:vendor_id)
  end
end
