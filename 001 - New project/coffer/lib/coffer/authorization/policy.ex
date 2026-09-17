defmodule Coffer.Authorization.Policy do
  @moduledoc """
  Central role-based authorization check. Every controller/LiveView action
  that mutates or views a restricted resource calls `can?/3` here instead of
  checking `user.role` ad hoc — keeps the 3-role matrix (spec §3.2) in one
  place so per-module granularity can replace it later without touching call
  sites.

  `resource` is a context-defined atom (e.g. `:role_mapping`, `:currency`,
  `:audit_log`); `action` is one of `:view`, `:create`, `:update`, `:delete`,
  `:export`.

  Note: `:currency`/`:exchange_rate` are deliberately NOT admin-only here —
  spec §3.2's literal text puts currency-rate management in the Admin-only
  column, but the user explicitly asked for Staff to have create/edit access
  the same as they do for ledger transactions (delete stays Admin-only,
  same as every other resource). `:role_mapping`, `:user`, and
  `:system_settings` remain admin-only per spec.
  """

  alias Coffer.Accounts.User

  @admin_only_resources [:role_mapping, :user, :system_settings]

  def can?(nil, _action, _resource), do: false
  def can?(%User{active: false}, _action, _resource), do: false
  def can?(%User{role: nil}, _action, _resource), do: false

  def can?(%User{role: :admin}, _action, _resource), do: true

  def can?(%User{role: :staff}, action, :audit_log) when action in [:view, :export], do: true

  def can?(%User{role: :read_only}, action, :audit_log) when action in [:view, :export],
    do: false

  def can?(%User{role: _}, _action, resource) when resource in @admin_only_resources,
    do: false

  def can?(%User{role: :staff}, :delete, _resource), do: false
  def can?(%User{role: :staff}, action, _resource) when action in [:create, :update], do: true

  def can?(%User{role: role}, action, _resource) when role in [:staff, :read_only, :admin],
    do: action in [:view, :export]

  def can?(_user, _action, _resource), do: false
end
