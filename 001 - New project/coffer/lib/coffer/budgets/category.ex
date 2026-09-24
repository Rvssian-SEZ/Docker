defmodule Coffer.Budgets.Category do
  use Coffer.Schema
  import Ecto.Changeset

  alias Coffer.Repo

  @max_depth 5

  schema "budget_categories" do
    field :name, :string
    field :position, :integer

    belongs_to :parent, __MODULE__
    has_many :children, __MODULE__, foreign_key: :parent_id

    timestamps(type: :utc_datetime)
  end

  def max_depth, do: @max_depth

  def changeset(category, attrs) do
    category
    |> cast(attrs, [:name, :parent_id])
    |> validate_required([:name])
    |> unique_constraint(:name)
    |> foreign_key_constraint(:parent_id)
    |> validate_hierarchy()
  end

  defp validate_hierarchy(changeset) do
    parent_id = get_field(changeset, :parent_id)
    self_id = get_field(changeset, :id)

    cond do
      is_nil(parent_id) ->
        changeset

      parent_id == self_id ->
        add_error(changeset, :parent_id, "a category can't be its own parent")

      creates_cycle?(parent_id, self_id) ->
        add_error(changeset, :parent_id, "that would create a circular category hierarchy")

      ancestor_depth(parent_id) + 1 > @max_depth ->
        add_error(
          changeset,
          :parent_id,
          "categories can only be nested #{@max_depth} levels deep"
        )

      true ->
        changeset
    end
  end

  # Walking up from the proposed parent: if we ever reach `self_id`, the
  # proposed parent is actually a descendant of the category being saved,
  # which would close a loop.
  defp creates_cycle?(parent_id, self_id), do: creates_cycle?(parent_id, self_id, 0)
  defp creates_cycle?(_parent_id, _self_id, guard) when guard > @max_depth + 1, do: false
  defp creates_cycle?(nil, _self_id, _guard), do: false
  defp creates_cycle?(parent_id, self_id, _guard) when parent_id == self_id, do: true

  defp creates_cycle?(parent_id, self_id, guard) do
    case Repo.get(__MODULE__, parent_id) do
      nil -> false
      %__MODULE__{parent_id: next} -> creates_cycle?(next, self_id, guard + 1)
    end
  end

  defp ancestor_depth(id), do: ancestor_depth(id, 0)
  defp ancestor_depth(_id, guard) when guard > @max_depth + 1, do: guard

  defp ancestor_depth(id, guard) do
    case Repo.get(__MODULE__, id) do
      nil -> 0
      %__MODULE__{parent_id: nil} -> 1
      %__MODULE__{parent_id: parent_id} -> 1 + ancestor_depth(parent_id, guard + 1)
    end
  end
end
