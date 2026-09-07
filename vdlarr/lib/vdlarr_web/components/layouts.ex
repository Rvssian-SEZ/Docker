defmodule VdlarrWeb.Layouts do
  use VdlarrWeb, :html

  embed_templates "layouts/*"
  embed_templates "layouts/partials/*"

  @doc """
  Whether the given sidebar `href` should be shown as the active nav item for the current
  request path. Plain prefix-matching, checked in a specific order by the caller (see
  sidebar.html.heex) so a more specific href (eg: "/sources/hidden") can claim a path before
  a broader one that would otherwise also match as a prefix (eg: "/sources", Dashboard).

  "/" is treated as equivalent to "/sources" for Dashboard specifically, since both routes
  render the same page (see the "Make Dashboard the default landing page" change).
  """
  def nav_active?(request_path, "/sources") do
    (request_path == "/" or String.starts_with?(request_path, "/sources")) and
      not String.starts_with?(request_path, "/sources/hidden")
  end

  def nav_active?(request_path, href), do: String.starts_with?(request_path, href)

  @doc """
  Renders a sidebar menu item link

  ## Examples

      <.sidebar_link icon="hero-home" text="Home" href="/" />
  """
  attr :icon, :string, required: true
  attr :text, :string, required: true
  attr :href, :any, required: true
  attr :target, :any, default: "_self"
  attr :icon_class, :string, default: ""
  attr :active, :boolean, default: false

  def sidebar_item(assigns) do
    ~H"""
    <li>
      <.sidebar_link icon={@icon} text={@text} href={@href} target={@target} icon_class={@icon_class} active={@active} />
    </li>
    """
  end

  @doc """
  Renders a sidebar menu item with a submenu

  ## Examples

      <.sidebar_submenu icon="hero-home" text="Home" current_path="/">
        <:submenu icon="hero-home" text="Home" href="/" />
      </.sidebar_submenu>
  """

  attr :icon, :string, required: true
  attr :text, :string, required: true
  attr :current_path, :string, required: true

  slot :submenu do
    attr :icon, :string
    attr :text, :string
    attr :href, :any
    attr :target, :any
  end

  def sidebar_submenu(assigns) do
    initially_selected = Enum.any?(assigns[:submenu], &(&1[:href] == assigns[:current_path]))
    assigns = Map.put(assigns, :initially_selected, initially_selected)

    ~H"""
    <li class="text-bodydark1" x-data={"{ selected: #{@initially_selected} }"}>
      <span
        class={[
          "font-medium cursor-pointer",
          "group relative flex items-center justify-between rounded-sm px-4 py-2 duration-300 ease-in-out",
          "duration-300 ease-in-out",
          "hover:bg-meta-4"
        ]}
        x-on:click="selected = !selected"
      >
        <span class="flex items-center gap-2.5">
          <.icon name={@icon} /> {@text}
        </span>
        <span class="text-bodydark2">
          <.icon name="hero-chevron-down" x-bind:class="{ 'rotate-180': selected }" />
        </span>
      </span>

      <ul x-cloak x-show="selected">
        <li :for={menu <- @submenu} class="text-bodydark2">
          <.sidebar_link icon={menu[:icon]} text={menu[:text]} href={menu[:href]} target={menu[:target]} class="pl-10" />
        </li>
      </ul>
    </li>
    """
  end

  @doc """
  Renders a sidebar menu item link

  ## Examples

      <.sidebar_link icon="hero-home" text="Home" href="/" />
  """
  attr :icon, :string
  attr :text, :string, required: true
  attr :href, :any, required: true
  attr :target, :any, default: "_self"
  attr :class, :string, default: ""
  attr :icon_class, :string, default: ""
  attr :active, :boolean, default: false

  def sidebar_link(assigns) do
    ~H"""
    <.link
      href={@href}
      target={@target}
      class={[
        "group relative flex items-center gap-2.5 rounded-lg px-3 py-2.5 border-l-2 transition-colors",
        if(@active,
          do: "text-white font-medium bg-gradient-to-r from-indigo-500/20 to-transparent border-indigo-400",
          else: "text-slate-400 font-medium hover:text-white hover:bg-white/5 border-transparent"
        ),
        @class
      ]}
    >
      <.icon :if={@icon} name={@icon} class={"#{@icon_class} #{if @active, do: "text-indigo-400", else: ""}"} />
      {@text}
    </.link>
    """
  end
end
