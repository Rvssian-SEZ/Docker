defmodule Coffer.Budgets do
  @moduledoc """
  Budget envelopes and their categories. Envelope "remaining balance" is
  always computed at query time from the ledger, never stored, to avoid
  drift (spec §4.3) — see `envelope_remaining/1`.
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Accounts.User
  alias Coffer.Ledger.Transaction
  alias Coffer.Budgets.{Category, Envelope}

  # --- Categories -----------------------------------------------------

  def list_categories, do: Repo.all(from c in Category, order_by: c.name)
  def get_category!(id), do: Repo.get!(Category, id)

  @doc """
  Categories ordered depth-first (each category immediately followed by its
  own descendants) with a `:depth` field (0 for top-level) — the order and
  depth a UI needs to render an indented tree from a flat `Enum.map`, without
  the template itself needing to know anything about the hierarchy.
  """
  def list_categories_tree do
    categories = list_categories()
    children_by_parent = Enum.group_by(categories, & &1.parent_id)

    children_by_parent
    |> Map.get(nil, [])
    |> Enum.flat_map(&flatten_subtree(&1, children_by_parent, 0))
  end

  defp flatten_subtree(category, children_by_parent, depth) do
    node = Map.put(category, :depth, depth)
    children = Map.get(children_by_parent, category.id, [])
    [node | Enum.flat_map(children, &flatten_subtree(&1, children_by_parent, depth + 1))]
  end

  @doc "A category's name prefixed with its ancestors, e.g. \"Operations > Office Supplies\"."
  def category_path_label(%Category{} = category, categories \\ list_categories()) do
    by_id = Map.new(categories, &{&1.id, &1})
    build_path_label(category, by_id, [category.name])
  end

  defp build_path_label(%Category{parent_id: nil}, _by_id, acc), do: Enum.join(acc, " > ")

  defp build_path_label(%Category{parent_id: parent_id}, by_id, acc) do
    case Map.get(by_id, parent_id) do
      nil -> Enum.join(acc, " > ")
      parent -> build_path_label(parent, by_id, [parent.name | acc])
    end
  end

  @doc """
  `category_id` plus every id in its subtree — for rolling a parent
  category's reported spend up to include its descendants' spend (see
  `Coffer.Reporting.spend_by_category/1`).
  """
  def category_and_descendant_ids(category_id, categories \\ list_categories()) do
    children_by_parent = Enum.group_by(categories, & &1.parent_id)
    collect_descendant_ids([category_id], children_by_parent, [category_id])
  end

  defp collect_descendant_ids([], _children_by_parent, acc), do: acc

  defp collect_descendant_ids([id | rest], children_by_parent, acc) do
    child_ids = children_by_parent |> Map.get(id, []) |> Enum.map(& &1.id)
    collect_descendant_ids(child_ids ++ rest, children_by_parent, child_ids ++ acc)
  end

  def change_category(%Category{} = category, attrs \\ %{}),
    do: Category.changeset(category, attrs)

  def create_category(attrs, %User{} = actor) do
    changeset = Category.changeset(%Category{}, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:category, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{category: c} ->
      AuditLog.record(actor.id, :create, "BudgetCategory", c.id, %{after: serialize_category(c)})
    end)
    |> Repo.transaction()
    |> unwrap(:category)
  end

  def update_category(%Category{} = category, attrs, %User{} = actor) do
    before = serialize_category(category)
    changeset = Category.changeset(category, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:category, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{category: c} ->
      AuditLog.record(actor.id, :update, "BudgetCategory", c.id, %{
        before: before,
        after: serialize_category(c)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:category)
  end

  def delete_category(%Category{} = category, %User{} = actor) do
    before = serialize_category(category)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:category, category)
    |> Ecto.Multi.run(:audit, fn _repo, %{category: c} ->
      AuditLog.record(actor.id, :delete, "BudgetCategory", c.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap(:category)
  end

  # --- Envelopes --------------------------------------------------------

  def list_envelopes do
    Envelope
    |> order_by(desc: :fiscal_year, asc: :name)
    |> preload([:category, :created_by])
    |> Repo.all()
  end

  @doc """
  Envelopes whose fiscal year overlaps `[date_from, date_to]` — every fiscal
  year is a fixed calendar-year block (`Coffer.FiscalYear`), so overlap
  reduces to a plain integer-year comparison. Backs the Dashboard's Envelope
  filter dropdown so it only offers envelopes that could actually have data
  in the selected date range, instead of every envelope ever created.
  """
  def list_envelopes_in_range(%Date{} = date_from, %Date{} = date_to) do
    Envelope
    |> where([e], e.fiscal_year >= ^date_from.year and e.fiscal_year <= ^date_to.year)
    |> order_by(desc: :fiscal_year, asc: :name)
    |> preload([:category, :created_by])
    |> Repo.all()
  end

  def list_envelopes(fiscal_year) do
    Envelope
    |> where(fiscal_year: ^fiscal_year)
    |> order_by(asc: :name)
    |> preload([:category, :created_by])
    |> Repo.all()
  end

  def get_envelope!(id), do: Repo.get!(Envelope, id) |> Repo.preload([:category, :created_by])

  def change_envelope(%Envelope{} = envelope, attrs \\ %{}),
    do: Envelope.changeset(envelope, attrs)

  def create_envelope(attrs, %User{} = actor) do
    changeset =
      %Envelope{}
      |> Envelope.changeset(attrs)
      |> Ecto.Changeset.put_change(:created_by_id, actor.id)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:envelope, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{envelope: e} ->
      AuditLog.record(actor.id, :create, "BudgetEnvelope", e.id, %{after: serialize_envelope(e)})
    end)
    |> Repo.transaction()
    |> unwrap(:envelope)
  end

  def update_envelope(%Envelope{} = envelope, attrs, %User{} = actor) do
    before = serialize_envelope(envelope)
    changeset = Envelope.changeset(envelope, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:envelope, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{envelope: e} ->
      AuditLog.record(actor.id, :update, "BudgetEnvelope", e.id, %{
        before: before,
        after: serialize_envelope(e)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:envelope)
  end

  def delete_envelope(%Envelope{} = envelope, %User{} = actor) do
    before = serialize_envelope(envelope)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:envelope, envelope)
    |> Ecto.Multi.run(:audit, fn _repo, %{envelope: e} ->
      AuditLog.record(actor.id, :delete, "BudgetEnvelope", e.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap(:envelope)
  end

  @doc """
  `allocated_amount` minus base-currency spend from EXPENSE transactions
  tagged to this envelope. Income transactions aren't netted against an
  envelope's remaining balance even if one is somehow tagged to one — an
  envelope models money set aside to spend, not a general running total, and
  spec §4.4 only expects expenses to carry a `budget_envelope_id` in
  practice ("income may not"). Computed at query time on every call, never
  stored (spec §4.3).
  """
  def envelope_remaining(%Envelope{} = envelope) do
    spent =
      Transaction
      |> where(budget_envelope_id: ^envelope.id, direction: :expense)
      |> select([t], sum(t.amount_base))
      |> Repo.one()
      |> Kernel.||(Decimal.new(0))

    Decimal.sub(envelope.allocated_amount, spent)
  end

  @doc """
  Copies every `active: true` envelope from the most recent fiscal year that
  has any envelope rows into fresh rows for `target_year`, carrying over
  `name`/`category_id`/`allocated_amount` as a starting point (admin
  adjusts from there) — no rollover of unspent balance (spec §4.3: "reset
  yearly"). Prior-year rows are never modified. Idempotent: a no-op if
  `target_year` already has any envelope rows, so the cron worker can safely
  re-run/catch up after downtime (spec §6) without duplicating.

  `actor_id` may be `nil` for the scheduled/system-triggered run; the
  on-demand admin action passes the triggering admin's id.
  """
  def rollover_fiscal_year(target_year, actor_id \\ nil) when is_integer(target_year) do
    if Repo.exists?(from e in Envelope, where: e.fiscal_year == ^target_year) do
      {:ok, :already_rolled_over}
    else
      case latest_prior_year_with_envelopes(target_year) do
        nil ->
          {:ok, :no_prior_year_envelopes}

        prior_year ->
          prior_year
          |> list_envelopes()
          |> Enum.filter(& &1.active)
          |> Enum.reduce_while({:ok, []}, fn envelope, {:ok, acc} ->
            attrs = %{
              "name" => envelope.name,
              "description" => envelope.description,
              "fiscal_year" => target_year,
              "allocated_amount" => envelope.allocated_amount,
              "category_id" => envelope.category_id
            }

            case create_envelope_as(attrs, actor_id) do
              {:ok, new_envelope} -> {:cont, {:ok, [new_envelope | acc]}}
              {:error, _} = error -> {:halt, error}
            end
          end)
          |> case do
            {:ok, created} -> {:ok, Enum.reverse(created)}
            error -> error
          end
      end
    end
  end

  defp create_envelope_as(attrs, actor_id) do
    changeset =
      %Envelope{}
      |> Envelope.changeset(attrs)
      |> Ecto.Changeset.put_change(:created_by_id, actor_id)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:envelope, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{envelope: e} ->
      AuditLog.record(actor_id, :create, "BudgetEnvelope", e.id, %{after: serialize_envelope(e)})
    end)
    |> Repo.transaction()
    |> unwrap(:envelope)
  end

  defp latest_prior_year_with_envelopes(target_year) do
    Envelope
    |> where([e], e.fiscal_year < ^target_year)
    |> select([e], max(e.fiscal_year))
    |> Repo.one()
  end

  defp serialize_category(%Category{} = c), do: %{id: c.id, name: c.name, parent_id: c.parent_id}

  defp serialize_envelope(%Envelope{} = e) do
    %{
      id: e.id,
      name: e.name,
      description: e.description,
      fiscal_year: e.fiscal_year,
      allocated_amount: Decimal.to_string(e.allocated_amount),
      category_id: e.category_id,
      active: e.active
    }
  end

  defp unwrap({:ok, %{envelope: result}}, :envelope), do: {:ok, result}
  defp unwrap({:ok, %{category: result}}, :category), do: {:ok, result}
  defp unwrap({:error, _failed_op, changeset, _changes}, _key), do: {:error, changeset}
end
