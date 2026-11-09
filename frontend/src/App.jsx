import React, { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useOutletContext } from "react-router-dom";
import { Bell, GraduationCap, LayoutDashboard, Users, UsersRound, FileText, Tags, CalendarRange, Gauge, Shuffle, BarChart3, History, ScrollText, Settings, LogOut, Menu, UserCog, UserCheck, Briefcase, ClipboardList, ChevronRight } from "lucide-react";
import { api } from "./api.js";
import { useAuth } from "./auth.jsx";
import { Spinner } from "./ui.jsx";
import { FacultyRegister, Login, ResetPassword, TeamRegister, homeFor } from "./pages/public.jsx";
import { Account, Notifications } from "./pages/shared.jsx";
import { LeaderDashboard, LeaderGuide, LeaderProposal, LeaderStatus, LeaderTeam } from "./pages/leader.jsx";
import { FacultyDashboard, FacultyProfilePage, FacultyTeams, FacultyWorkload } from "./pages/faculty.jsx";
import { AdminAllocation, AdminAudit, AdminCycles, AdminDashboard, AdminDomains, AdminFaculty, AdminHistory, AdminProposals, AdminReports, AdminSettings, AdminTeamComposition, AdminTeamMentor, AdminTeams, AdminWorkload } from "./pages/admin.jsx";

const NAV = {
  admin: [
    ["Overview", [["/admin", "Dashboard", LayoutDashboard, true]]],
    ["Allocation", [["/admin/allocation", "Guide allocation", Shuffle], ["/admin/workload", "Workload management", Gauge], ["/admin/history", "Allocation history", History]]],
    ["People", [["/admin/faculty", "Faculty management", Users], ["/admin/teams", "Team management", UsersRound], ["/admin/proposals", "Proposal review", FileText]]],
    ["Configuration", [["/admin/domains", "Domain management", Tags], ["/admin/cycles", "Academic cycles", CalendarRange], ["/admin/settings", "System settings", Settings]]],
    ["Insight", [["/admin/reports", "Reports", BarChart3, true], ["/admin/reports/team-composition", "Team composition", UsersRound], ["/admin/reports/team-mentor", "Team–mentor report", UserCheck], ["/admin/audit", "Audit logs", ScrollText]]],
    ["Account", [["/admin/notifications", "Notifications", Bell], ["/admin/account", "Account", UserCog]]]],
  team_leader: [
    ["Team", [["/team", "Dashboard", LayoutDashboard, true], ["/team/details", "Team details", UsersRound], ["/team/proposal", "Project proposal", FileText],
      ["/team/status", "Proposal status", ClipboardList], ["/team/guide", "Allocated guide", UserCheck]]],
    ["Account", [["/team/notifications", "Notifications", Bell], ["/team/account", "Account", UserCog]]]],
  faculty: [
    ["Faculty", [["/faculty", "Dashboard", LayoutDashboard, true], ["/faculty/profile", "Profile & expertise", UserCog], ["/faculty/teams", "Assigned teams", UsersRound],
      ["/faculty/workload", "Workload & capacity", Briefcase]]],
    ["Account", [["/faculty/notifications", "Notifications", Bell], ["/faculty/account", "Account", UserCog]]]],
};

const WORKSPACE = { admin: "Admin console", team_leader: "Team workspace", faculty: "Faculty workspace" };
const initials = (n) => (n || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

function Shell({ role }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const loc = useLocation();
  const nav = useNavigate();
  const refresh = useCallback(() => api("/notifications/unread-count").then((r) => setUnread(r.unread)).catch(() => {}), []);
  useEffect(() => { refresh(); setOpen(false); }, [loc.pathname, refresh]);
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={homeFor(user)} replace />;
  const base = homeFor(user);
  const flat = NAV[role].flatMap(([, links]) => links);
  const here = (flat.find(([to]) => to === loc.pathname) || flat.find(([to, , , end]) => !end && loc.pathname.startsWith(to)) || flat[0])[1];
  return (
    <div className="shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <div className={`scrim ${open ? "show" : ""}`} onClick={() => setOpen(false)} aria-hidden="true" />
      <nav className={`sidebar ${open ? "open" : ""}`} aria-label="Main navigation">
        <div className="brand"><span className="logo"><GraduationCap size={18} aria-hidden /></span><span>GuideAllocate<small>{WORKSPACE[role]}</small></span></div>
        <div className="nav">
          {NAV[role].map(([section, links]) => (
            <React.Fragment key={section}>
              <div className="sec" aria-hidden="true">{section}</div>
              {links.map(([to, label, Icon, end]) => (
                <NavLink key={to} to={to} end={end}><Icon size={17} aria-hidden />{label}
                  {label === "Notifications" && unread > 0 && <span className="count" aria-label={`${unread} unread`}>{unread}</span>}</NavLink>))}
            </React.Fragment>))}
        </div>
      </nav>
      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setOpen(!open)} aria-label="Toggle navigation menu" aria-expanded={open}><Menu size={20} /></button>
          <div className="crumbs" aria-label="Breadcrumb"><span className="crumb-sec">{WORKSPACE[role]}</span><ChevronRight size={14} aria-hidden /><b>{here}</b></div>
          <div className="row">
            <button className="icon-btn bell" onClick={() => nav(`${base}/notifications`)} aria-label={`Notifications, ${unread} unread`}><Bell size={19} />{unread > 0 && <span className="dot" aria-hidden>{unread}</span>}</button>
            <span className="avatar" aria-hidden="true">{initials(user.full_name)}</span><div className="who"><b>{user.full_name}</b><span className="role-chip">{user.role.replace("_", " ")}</span></div>
            <button className="btn sm" onClick={() => { logout(); nav("/login"); }}><LogOut size={14} aria-hidden /> Sign out</button>
          </div>
        </header>
        <main className="content" id="main" tabIndex={-1}><div className="page-enter" key={loc.pathname}><Outlet context={{ refreshUnread: refresh }} /></div></main>
      </div>
    </div>
  );
}

function Notes() {
  const { refreshUnread } = useOutletContext();
  return <Notifications onChange={refreshUnread} />;
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner label="Restoring session…" />;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register/team" element={<TeamRegister />} />
      <Route path="/register/faculty" element={<FacultyRegister />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/team" element={<Shell role="team_leader" />}>
        <Route index element={<LeaderDashboard />} /><Route path="details" element={<LeaderTeam />} /><Route path="proposal" element={<LeaderProposal />} />
        <Route path="status" element={<LeaderStatus />} /><Route path="guide" element={<LeaderGuide />} /><Route path="notifications" element={<Notes />} /><Route path="account" element={<Account />} />
      </Route>
      <Route path="/faculty" element={<Shell role="faculty" />}>
        <Route index element={<FacultyDashboard />} /><Route path="profile" element={<FacultyProfilePage />} /><Route path="teams" element={<FacultyTeams />} />
        <Route path="workload" element={<FacultyWorkload />} /><Route path="notifications" element={<Notes />} /><Route path="account" element={<Account />} />
      </Route>
      <Route path="/admin" element={<Shell role="admin" />}>
        <Route index element={<AdminDashboard />} /><Route path="faculty" element={<AdminFaculty />} /><Route path="teams" element={<AdminTeams />} />
        <Route path="proposals" element={<AdminProposals />} /><Route path="domains" element={<AdminDomains />} /><Route path="cycles" element={<AdminCycles />} />
        <Route path="workload" element={<AdminWorkload />} /><Route path="allocation" element={<AdminAllocation />} /><Route path="reports" element={<AdminReports />} /><Route path="reports/team-composition" element={<AdminTeamComposition />} /><Route path="reports/team-mentor" element={<AdminTeamMentor />} />
        <Route path="history" element={<AdminHistory />} /><Route path="audit" element={<AdminAudit />} /><Route path="settings" element={<AdminSettings />} />
        <Route path="notifications" element={<Notes />} /><Route path="account" element={<Account />} />
      </Route>
      <Route path="*" element={<Navigate to={user ? homeFor(user) : "/login"} replace />} />
    </Routes>
  );
}
