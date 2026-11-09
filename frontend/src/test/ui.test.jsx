import React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as apiMod from "../api.js";
import { ConfirmProvider, ToastProvider, validateWholeNumber, UtilBar } from "../ui.jsx";
import { ApproveDialog, CapacityDialog } from "../pages/admin_faculty.jsx";
import { OverrideDialog, PreviewResults } from "../pages/admin_allocation.jsx";

const wrap = (ui) => render(<MemoryRouter><ToastProvider><ConfirmProvider>{ui}</ConfirmProvider></ToastProvider></MemoryRouter>);
const fac = { id: 5, full_name: "Dr Rao", designation: "Professor", department: "CSE", requested_capacity: 4, suggested_capacity: 6 };

describe("validateWholeNumber (mirrors the server)", () => {
  const v = (x, o = {}) => validateWholeNumber(x, { min: 1, max: 100, ...o });
  it("accepts whole numbers in range", () => { expect(v("1")).toBe(""); expect(v("100")).toBe(""); expect(v(" 7 ")).toBe(""); });
  it.each([["", /Enter/], ["0", /at least 1/], ["-2", /at least 1/], ["101", /more than 100/], ["2.5", /whole number/], ["abc", /whole number/], ["1e2", /whole number/]])(
    "rejects %s", (x, re) => expect(v(x)).toMatch(re));
  it("flags browser badInput", () => expect(v("", { badInput: true })).toMatch(/whole number/));
});

describe("ApproveDialog", () => {
  it("renders capacity as an accessible number input, empty by default", () => {
    wrap(<ApproveDialog faculty={fac} limits={{ min: 1, max: 30 }} onClose={() => {}} onDone={() => {}} />);
    const input = screen.getByLabelText(/project supervision capacity/i);
    expect(input).toHaveAttribute("type", "number");
    expect(input).toHaveAttribute("min", "1"); expect(input).toHaveAttribute("max", "30"); expect(input).toHaveAttribute("step", "1");
    expect(input).toHaveValue(null);                       // never silently pre-assigned
    expect(input).toHaveAttribute("placeholder", "e.g. 6");
  });
  it("shows a field error beside the input and does not call the API for invalid values", async () => {
    const spy = vi.spyOn(apiMod, "api").mockResolvedValue({});
    wrap(<ApproveDialog faculty={fac} limits={{ min: 1, max: 30 }} onClose={() => {}} onDone={() => {}} />);
    const input = screen.getByLabelText(/project supervision capacity/i);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /approve faculty/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Enter the maximum/);
    await user.type(input, "0"); await user.click(screen.getByRole("button", { name: /approve faculty/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least 1/);
    await user.clear(input); await user.type(input, "31"); await user.click(screen.getByRole("button", { name: /approve faculty/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/more than 30/);
    await user.clear(input); await user.type(input, "2.5"); await user.click(screen.getByRole("button", { name: /approve faculty/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/whole number/);
    expect(spy).not.toHaveBeenCalled();
  });
  it("submits the numeric capacity (a Number, not text) to the approve endpoint", async () => {
    const spy = vi.spyOn(apiMod, "api").mockResolvedValue({ capacity: 8 });
    const done = vi.fn();
    wrap(<ApproveDialog faculty={fac} limits={{ min: 1, max: 30 }} onClose={() => {}} onDone={done} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/project supervision capacity/i), "8");
    await user.click(screen.getByRole("button", { name: /approve faculty/i }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith("/admin/faculty/5/approve", { method: "POST", body: { capacity: 8, remarks: "" } });
  });
  it("quick-fill buttons fill the field only on request", async () => {
    wrap(<ApproveDialog faculty={fac} onClose={() => {}} onDone={() => {}} />);
    await userEvent.setup().click(screen.getByRole("button", { name: /use requested \(4\)/i }));
    expect(screen.getByLabelText(/project supervision capacity/i)).toHaveValue(4);
  });
  it("shows a server-side field error next to the input", async () => {
    const err = Object.assign(new Error("capacity: nope"), { fieldErrors: { capacity: "Capacity cannot be more than 5." } });
    vi.spyOn(apiMod, "api").mockRejectedValue(err);
    wrap(<ApproveDialog faculty={fac} limits={{ min: 1, max: 100 }} onClose={() => {}} onDone={() => {}} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/project supervision capacity/i), "9");
    await user.click(screen.getByRole("button", { name: /approve faculty/i }));
    expect(await screen.findByText(/cannot be more than 5/)).toBeInTheDocument();
  });
});

describe("CapacityDialog", () => {
  it("warns about overload without removing teams and requires acknowledgement", async () => {
    wrap(<CapacityDialog faculty={{ id: 1, name: "Dr Rao", assigned: 4, max_capacity: 5 }} limits={{ min: 1, max: 100 }} onClose={() => {}} onSaved={() => {}} />);
    const user = userEvent.setup();
    const input = screen.getByLabelText(/maximum projects/i);
    await user.clear(input); await user.type(input, "2");
    expect(screen.getByText(/2 over capacity/)).toBeInTheDocument();
    expect(screen.getByText(/not removed or reassigned/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save capacity/i })).toBeDisabled();
    await user.click(screen.getByLabelText(/i understand/i));
    await user.type(screen.getByLabelText(/reason for the change/i), "Sabbatical");
    expect(screen.getByRole("button", { name: /save capacity/i })).toBeEnabled();
  });
});

const check = (over = {}) => ({ team_id: 1, team_name: "Team A", faculty_id: 9, faculty_name: "Dr Iot", current_faculty: null, is_reassignment: false,
  allocation_finalised: false, score: 0, explanation: "No compatible domain match", match_tier: "none", matched_domains: [], domain_compatible: false,
  team_domains: { primary: "Cybersecurity", additional: ["Robotics"] }, faculty_domains: { expertise: ["IoT"], supported: [], interest: [] },
  faculty_assigned_before: 2, faculty_capacity: 2, faculty_projected: 3, projected_overload: 1, capacity_exceeded: true, warnings: [], problems: [],
  can_assign: true, requires_domain_override: true, requires_overload_ack: true, requires_reason: true, is_override: true, ...over });

describe("OverrideDialog", () => {
  it("shows the prominent warning, both domain lists and blocks confirm until reason + acknowledgements", async () => {
    vi.spyOn(apiMod, "api").mockResolvedValue(check());
    wrap(<OverrideDialog teamId={1} facultyId={9} onClose={() => {}} onDone={() => {}} />);
    expect(await screen.findByText(/No compatible domain\./)).toBeInTheDocument();
    expect(screen.getByText(/Exceeds nominal capacity/)).toBeInTheDocument();
    expect(screen.getByText("Cybersecurity")).toBeInTheDocument(); expect(screen.getByText("IoT")).toBeInTheDocument();
    const go = screen.getByRole("button", { name: /confirm override/i });
    expect(go).toBeDisabled();
    const user = userEvent.setup();
    await user.click(screen.getByLabelText(/overrides domain compatibility/i));
    await user.click(screen.getByLabelText(/exceeds the mentor's capacity/i));
    expect(go).toBeDisabled();                                   // reason still missing
    await user.type(screen.getByLabelText(/override reason/i), "Only mentor free");
    expect(go).toBeEnabled();
  });
  it("posts the explicit override flags and reason", async () => {
    const spy = vi.spyOn(apiMod, "api").mockImplementation(async (path) => (path.includes("manual-preview") ? check() : { ok: true }));
    const done = vi.fn();
    wrap(<OverrideDialog teamId={1} facultyId={9} onClose={() => {}} onDone={done} />);
    const user = userEvent.setup();
    await screen.findByText(/No compatible domain\./);
    await user.click(screen.getByLabelText(/overrides domain compatibility/i)); await user.click(screen.getByLabelText(/exceeds the mentor's capacity/i));
    await user.type(screen.getByLabelText(/override reason/i), "Only mentor free");
    await user.click(screen.getByRole("button", { name: /confirm override/i }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(spy).toHaveBeenLastCalledWith("/admin/allocation/manual", { method: "POST", body: { team_id: 1, faculty_id: 9, reason: "Only mentor free", confirm: true, override_domain: true, acknowledge_overload: true } });
  });
  it("needs no acknowledgement or reason for an ordinary compatible assignment", async () => {
    vi.spyOn(apiMod, "api").mockResolvedValue(check({ requires_domain_override: false, requires_overload_ack: false, requires_reason: false, is_override: false,
      domain_compatible: true, match_tier: "primary", capacity_exceeded: false, faculty_projected: 2, projected_overload: 0 }));
    wrap(<OverrideDialog teamId={1} facultyId={9} onClose={() => {}} onDone={() => {}} />);
    expect(await screen.findByRole("button", { name: /^assign$/i })).toBeEnabled();
    expect(screen.queryByText(/No compatible domain\./)).toBeNull();
  });
  it("shows hard blockers that cannot be overridden", async () => {
    vi.spyOn(apiMod, "api").mockResolvedValue(check({ can_assign: false, problems: ["faculty marked unavailable"] }));
    wrap(<OverrideDialog teamId={1} facultyId={9} onClose={() => {}} onDone={() => {}} />);
    expect(await screen.findByText(/cannot be overridden/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm override/i })).toBeDisabled();
  });
});

const pv = {
  id: 1, policy: ["1. Give every team a compatible mentor."], solver: { proved_optimal: true },
  summary: { teams_assigned: 3, tier_counts: { primary: 2, additional: 1, related: 0 }, total_overload: 1, max_overload: 1, overloaded_faculty: 1, new_overload: 1, capacity_shortage: 0 },
  unassigned: [{ team_id: 9, team_name: "Lost Team", project_title: "x", reason: "No compatible", suggestions: [], team_interests: [] }],
  faculty_projection: [{ faculty_id: 1, name: "Dr One", department: "CSE", capacity: 1, current: 0, projected: 2, added: 2, overload: 1 }],
  assignments: [
    { team_id: 1, team_name: "Alpha", project_title: "p1", team_domain: "Cyber", team_interests: [], faculty_id: 1, faculty_name: "Dr One", tier: "primary", tier_rank: 1, score: 80, matched_domains: [{ domain: "Cyber", match: "exact" }], faculty_current: 0, faculty_capacity: 1, faculty_projected: 2, overload: 1, overload_warning: "Dr One will carry 2 teams against a capacity of 1 (+1)", change: "new", alternative_reason: null },
    { team_id: 2, team_name: "Beta", project_title: "p2", team_domain: "Cyber", team_interests: ["IoT"], faculty_id: 1, faculty_name: "Dr One", tier: "primary", tier_rank: 1, score: 70, matched_domains: [], faculty_current: 0, faculty_capacity: 1, faculty_projected: 2, overload: 1, overload_warning: "x", change: "new", alternative_reason: null },
    { team_id: 3, team_name: "Gamma", project_title: "p3", team_domain: "Robotics", team_interests: [], faculty_id: 2, faculty_name: "Dr Two", tier: "additional", tier_rank: 2, score: 40, matched_domains: [], faculty_current: 0, faculty_capacity: 3, faculty_projected: 1, overload: 0, overload_warning: null, change: "new", alternative_reason: "Primary-domain mentor(s) Dr One (2/1) are at or over capacity" },
  ],
};
describe("PreviewResults", () => {
  it("lists tiers, overload warnings, alternative-mentor reasons and unresolved teams", () => {
    render(<PreviewResults pv={pv} onCommit={() => {}} />);
    expect(screen.getAllByText(/primary match/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/against a capacity of 1/).length).toBeGreaterThan(0);
    expect(screen.getByText(/at or over capacity/)).toBeInTheDocument();
    expect(screen.getByText("Lost Team")).toBeInTheDocument();
    expect(screen.getByText(/1 team\(s\) require administrative resolution/)).toBeInTheDocument();
  });
  it("filters by search, tier, mentor and overload and sorts", async () => {
    render(<PreviewResults pv={pv} onCommit={() => {}} />);
    const user = userEvent.setup();
    const rows = () => within(screen.getAllByRole("table")[0]).getAllByRole("row").length - 1;
    expect(rows()).toBe(3);
    await user.selectOptions(screen.getByLabelText(/filter by match tier/i), "additional"); expect(rows()).toBe(1);
    await user.selectOptions(screen.getByLabelText(/filter by match tier/i), ""); await user.type(screen.getByLabelText(/search proposed/i), "beta"); expect(rows()).toBe(1);
    await user.clear(screen.getByLabelText(/search proposed/i)); await user.click(screen.getByLabelText(/overload only/i)); expect(rows()).toBe(2);
    await user.click(screen.getByLabelText(/overload only/i));
    await user.selectOptions(screen.getByLabelText(/sort by/i), "score");
    expect(within(screen.getAllByRole("table")[0]).getAllByRole("row")[1]).toHaveTextContent("Alpha");
    await user.selectOptions(screen.getByLabelText(/filter by mentor/i), "2"); expect(rows()).toBe(1);
  });
  it("empty state when filters match nothing", async () => {
    render(<PreviewResults pv={pv} onCommit={() => {}} />);
    await userEvent.setup().type(screen.getByLabelText(/search proposed/i), "zzz");
    expect(screen.getByText(/No assignments match your filters/)).toBeInTheDocument();
  });
});

describe("UtilBar", () => {
  it("states overload in text, not colour alone", () => {
    render(<UtilBar assigned={3} capacity={2} />);
    expect(screen.getByText(/\+1 over/)).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", expect.stringContaining("1 over capacity"));
  });
});
