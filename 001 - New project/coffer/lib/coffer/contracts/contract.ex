defmodule Coffer.Contracts.Contract do
  use Coffer.Schema
  import Ecto.Changeset

  @contract_types [:one_time, :subscription]
  @renewal_frequencies [:monthly, :quarterly, :annually, :custom]
  @statuses [:active, :expired, :cancelled]

  schema "contracts" do
    field :name, :string
    field :contract_type, Ecto.Enum, values: @contract_types
    field :start_date, :date
    field :end_date, :date
    field :renewal_date, :date
    field :renewal_frequency, Ecto.Enum, values: @renewal_frequencies
    field :amount, :decimal
    field :auto_post_to_ledger, :boolean, default: false
    field :status, Ecto.Enum, values: @statuses, default: :active
    field :last_notified_tier, :integer
    field :notes, :string

    belongs_to :vendor, Coffer.Vendors.Vendor
    belongs_to :currency, Coffer.Currencies.Currency
    belongs_to :budget_envelope, Coffer.Budgets.Envelope
    belongs_to :created_by, Coffer.Accounts.User
    has_many :attachments, Coffer.Contracts.Attachment

    timestamps(type: :utc_datetime)
  end

  def contract_types, do: @contract_types
  def renewal_frequencies, do: @renewal_frequencies
  def statuses, do: @statuses

  @doc """
  User-facing fields only — `created_by_id` is set from the authenticated
  actor, `last_notified_tier` is only ever written by
  `Coffer.Contracts.ContractRenewalWorker`'s own logic, never form/API input.
  """
  def changeset(contract, attrs) do
    contract
    |> cast(attrs, [
      :name,
      :vendor_id,
      :contract_type,
      :start_date,
      :end_date,
      :renewal_date,
      :renewal_frequency,
      :amount,
      :currency_id,
      :budget_envelope_id,
      :auto_post_to_ledger,
      :status,
      :notes
    ])
    |> validate_required([:name, :vendor_id, :contract_type, :start_date, :amount, :currency_id])
    |> validate_number(:amount, greater_than: 0)
    |> foreign_key_constraint(:vendor_id)
    |> foreign_key_constraint(:currency_id)
    |> foreign_key_constraint(:budget_envelope_id)
  end

  @doc "Used only by the renewal worker to advance the cycle / reset tier tracking."
  def system_changeset(contract, attrs) do
    cast(contract, attrs, [:renewal_date, :last_notified_tier])
  end
end
