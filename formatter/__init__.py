"""Jarvis formatter: rich-powered terminal dashboards and plain-text output.

Usage:
    from formatter import tables, cards, brief, dashboard

    # Render a table
    output = tables.render(
        title="Calendar",
        columns=["Time", "Event"],
        rows=[("8:30 AM", "ePMLT")],
        mode="terminal",
    )

    # Render a status card
    output = cards.render(
        title="RBAC Status",
        status="yellow",
        fields={"Owner": "Shawn", "Progress": "5%"},
        mode="terminal",
    )
"""
