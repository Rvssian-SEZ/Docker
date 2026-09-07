defmodule VdlarrWeb do
  @moduledoc """
  The entrypoint for defining your web interface, such
  as controllers, components, channels, and so on.

  This can be used in your application as:

      use VdlarrWeb, :controller
      use VdlarrWeb, :html

  The definitions below will be executed for every controller,
  component, etc, so keep them short and clean, focused
  on imports, uses and aliases.

  Do NOT define functions inside the quoted expressions
  below. Instead, define additional modules and import
  those modules here.
  """

  def static_paths, do: ~w(assets fonts images favicon.ico robots.txt)

  def router do
    quote do
      use Phoenix.Router, helpers: true

      # Import common connection and controller functions to use in pipelines
      import Plug.Conn
      import Phoenix.Controller
      import Phoenix.LiveView.Router
    end
  end

  def channel do
    quote do
      use Phoenix.Channel
    end
  end

  def controller do
    quote do
      use Phoenix.Controller,
        formats: [:html, :json],
        layouts: [html: VdlarrWeb.Layouts]

      import Plug.Conn
      use Gettext, backend: VdlarrWeb.Gettext

      alias Vdlarr.Settings
      alias VdlarrWeb.Layouts

      unquote(verified_routes())
    end
  end

  def live_view do
    quote do
      use Phoenix.Component, global_prefixes: ~w(x-)

      use Phoenix.LiveView

      alias Vdlarr.Settings

      unquote(html_helpers())
    end
  end

  def live_component do
    quote do
      use Phoenix.LiveComponent

      alias Vdlarr.Settings

      unquote(html_helpers())
    end
  end

  def html do
    quote do
      use Phoenix.Component, global_prefixes: ~w(x-)

      # Import convenience functions from controllers
      import Phoenix.Controller,
        only: [get_csrf_token: 0, view_module: 1, view_template: 1]

      alias Vdlarr.Settings

      # Include general helpers for rendering HTML
      unquote(html_helpers())
    end
  end

  defp html_helpers do
    quote do
      # HTML escaping functionality
      import Phoenix.HTML
      # Core UI components and translation
      use Gettext, backend: VdlarrWeb.Gettext
      import VdlarrWeb.CoreComponents
      import VdlarrWeb.CustomComponents.TabComponents
      import VdlarrWeb.CustomComponents.TextComponents
      import VdlarrWeb.CustomComponents.TableComponents
      import VdlarrWeb.CustomComponents.ButtonComponents
      import Vdlarr.Utils.StringUtils, only: [double_brace: 1]

      alias Vdlarr.Settings
      alias Vdlarr.Utils.StringUtils

      # Shortcut for generating JS commands
      alias Phoenix.LiveView.JS

      # Routes generation with the ~p sigil
      unquote(verified_routes())
    end
  end

  def verified_routes do
    quote do
      use Phoenix.VerifiedRoutes,
        endpoint: VdlarrWeb.Endpoint,
        router: VdlarrWeb.Router,
        statics: VdlarrWeb.static_paths()
    end
  end

  @doc """
  When used, dispatch to the appropriate controller/view/etc.
  """
  defmacro __using__(which) when is_atom(which) do
    apply(__MODULE__, which, [])
  end
end
