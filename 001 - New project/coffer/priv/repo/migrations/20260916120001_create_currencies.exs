defmodule Coffer.Repo.Migrations.CreateCurrencies do
  use Ecto.Migration

  def change do
    create table(:currencies, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :code, :string, null: false
      add :name, :string, null: false
      add :symbol, :string, null: false
      add :is_base, :boolean, null: false, default: false

      timestamps(type: :utc_datetime)
    end

    create unique_index(:currencies, [:code])

    create unique_index(:currencies, [:is_base],
             where: "is_base = true",
             name: :currencies_single_base_currency_index
           )
  end
end
