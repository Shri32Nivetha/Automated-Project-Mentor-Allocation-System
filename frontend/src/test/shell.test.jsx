import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Gauge } from "lucide-react";
import { describe, expect, it } from "vitest";
import { ConfirmProvider, Empty, Stat, ToastProvider, useConfirm, Alert } from "../ui.jsx";

describe("Stat", () => {
  it("renders label, value, sub text and an optional icon chip", () => {
    const { container } = render(<Stat label="Capacity" value={12} sub="of 20" tone="ok" icon={Gauge} />);
    expect(screen.getByText("Capacity")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("of 20")).toBeInTheDocument();
    expect(container.querySelector(".stat.ok .stat-ico svg")).not.toBeNull();
  });
  it("still works without an icon (label dot is drawn by CSS)", () => {
    const { container } = render(<Stat label="Plain" value="—" />);
    expect(container.querySelector(".stat-ico")).toBeNull();
    expect(screen.getByText("Plain")).toBeInTheDocument();
  });
});

describe("Empty", () => {
  it("shows an icon, title and message", () => {
    const { container } = render(<Empty title="Nothing here">Add something to begin.</Empty>);
    expect(container.querySelector(".empty-ico svg")).not.toBeNull();
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Add something to begin.")).toBeInTheDocument();
  });
});

describe("Alert", () => {
  it("uses an assertive role for errors/warnings and a polite one otherwise", () => {
    render(<><Alert tone="error">bad</Alert><Alert tone="info">fyi</Alert></>);
    expect(screen.getByText("bad").closest("[role]")).toHaveAttribute("role", "alert");
    expect(screen.getByText("fyi").closest("[role]")).toHaveAttribute("role", "status");
  });
});

function Ask() {
  const confirm = useConfirm();
  const [res, setRes] = React.useState("");
  return <><button onClick={async () => setRes(JSON.stringify(await confirm({ title: "Reject", message: "Sure?", reasonRequired: true, danger: true })))}>open</button><output>{res}</output></>;
}

describe("Confirm dialog", () => {
  it("keeps keyboard focus in the reason box while typing (no focus stealing on re-render)", async () => {
    render(<ToastProvider><ConfirmProvider><Ask /></ConfirmProvider></ToastProvider>);
    const user = userEvent.setup();
    await user.click(screen.getByText("open"));
    const box = await screen.findByLabelText(/reason/i);
    await user.type(box, "needs more detail");
    expect(box).toHaveFocus();
    expect(box).toHaveValue("needs more detail");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(document.querySelector("output").textContent).toContain("needs more detail");
  });
  it("requires a reason before the confirm button is enabled and closes on Escape", async () => {
    render(<ToastProvider><ConfirmProvider><Ask /></ConfirmProvider></ToastProvider>);
    const user = userEvent.setup();
    await user.click(screen.getByText("open"));
    expect(await screen.findByRole("button", { name: "Confirm" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("traps Tab inside the dialog", async () => {
    render(<ToastProvider><ConfirmProvider><Ask /></ConfirmProvider></ToastProvider>);
    const user = userEvent.setup();
    await user.click(screen.getByText("open"));
    await screen.findByRole("dialog");
    for (let i = 0; i < 6; i++) await user.tab();
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });
});
