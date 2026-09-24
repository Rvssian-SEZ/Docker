defmodule Coffer.Repo.Migrations.CreateContracts do
  use Ecto.Migration

  def change do
    create table(:contracts, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :name, :string, null: false
      add :vendor_id, references(:vendors, type: :binary_id, on_delete: :restrict), null: false
      add :contract_type, :string, null: false
      add :start_date, :date, null: false
      add :end_date, :date
      add :renewal_date, :date
      add :renewal_frequency, :string

      add :amount, :decimal, null: false

      add :currency_id, references(:currencies, type: :binary_id, on_delete: :restrict),
        null: false

      add :budget_envelope_id,
          references(:budget_envelopes, type: :binary_id, on_delete: :nilify_all)

      add :auto_post_to_ledger, :boolean, null: false, default: false
      add :status, :string, null: false, default: "active"

      # Tracks the renewal-reminder tier (30/14/7 days out, or 0 = due today
      # or overdue) already notified for the CURRENT renewal cycle, so
      # ContractRenewalWorker doesn't re-fire the same reminder every day it
      # runs — reset to null whenever renewal_date advances to a new cycle.
      add :last_notified_tier, :integer

      add :created_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :notes, :text

      timestamps(type: :utc_datetime)
    end

    create index(:contracts, [:vendor_id])
    create index(:contracts, [:renewal_date])
    create index(:contracts, [:status])

    create constraint(:contracts, :contract_type_must_be_valid,
             check: "contract_type IN ('one_time', 'subscription')"
           )

    create constraint(:contracts, :renewal_frequency_must_be_valid,
             check: "renewal_frequency IN ('monthly', 'quarterly', 'annually', 'custom')"
           )

    create constraint(:contracts, :status_must_be_valid,
             check: "status IN ('active', 'expired', 'cancelled')"
           )

    create constraint(:contracts, :amount_must_be_positive, check: "amount > 0")
  end
end
