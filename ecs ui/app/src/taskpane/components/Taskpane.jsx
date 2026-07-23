import React from "react";
import { Spin, Result, Button, Layout, Typography, Space, Avatar, Dropdown, Menu } from "antd";
import { LogoutOutlined, UserOutlined, SettingOutlined } from "@ant-design/icons";
import { useAuth } from "../contexts/AuthContext";
import SelectDeliverable from "./SelectDeliverable";
import { useRole } from "../contexts/RoleContext";
import { Frontend_LOCAL_PROXY } from "../../../constant";
import "./Taskpane.css";

const { Header } = Layout;
const { Text } = Typography;

const allowedRoles = [
  "SYSTEM_SUPPORT_ADMIN",
  "BUSINESS_ADMIN",
  "SUPER_ADMIN",
];

const openMonitoringDialog = (user) => {
  Office.context.ui.displayDialogAsync(
    `${Frontend_LOCAL_PROXY}/MonitoringDialog.html`,
    {
      height: 90,
      width: 90,
    },
    (result) => {
      if (result.status === Office.AsyncResultStatus.Failed) {
        console.error(result.error);
        return;
      }

      const dialog = result.value;

      dialog.addEventHandler(
        Office.EventType.DialogMessageReceived,
        (args) => {
          const data = JSON.parse(args.message);

          if (data.action === "ready") {
            dialog.messageChild(
              JSON.stringify({
                action: "init",
                payload: {
                  user,
                },
              })
            );
          }

          if (data.action === "close") {
            dialog.close();
          }
        }
      );
    }
  );
};

// Reusable centered wrapper
const Centered = ({ children }) => (
  <div
    style={{
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      height: "100vh",
      width: "100%",
    }}
  >
    {children}
  </div>
);

const Taskpane = () => {

  const { user, token, loading, error, login, logout } = useAuth();
  const { setUserSelected, selectedRole, selectedProject, monitoringSelected, setMonitoringSelected } = useRole();

  console.log("selectedRole, selectedProject: ", selectedRole, selectedProject)
  console.log("condition: ", allowedRoles.includes(selectedRole) && selectedProject?.project_name === "CCM")

  const settingsMenu = (
    <Menu
      items={[
        {
          key: "preferences",
          label: (
            <div
              onClick={() => {
                setMonitoringSelected(false);
                setUserSelected(true);
              }}
              style={{ cursor: "pointer" }}
            >
              Users
            </div>
          ),
        },

        ...(selectedRole === "SUPER_ADMIN"
          ? [
            {
              key: "monitoring",
              label: (
                <div
                  onClick={() => openMonitoringDialog(user)}
                  style={{ cursor: "pointer" }}
                >
                  Monitoring
                </div>
              ),
            },
          ]
          : []),
      ]}
    />
  );

  if (loading) {
    return (
      <Centered>
        <Spin tip="Loading authentication..." size="small" />
      </Centered>
    );
  }

  if (error) {
    return (
      <Centered>
        <Result
          status="error"
          title="Authentication failed"
          subTitle={error}
          extra={
            <Button type="primary" onClick={login}>
              Retry Login
            </Button>
          }
        />
      </Centered>
    );
  }

  if (!user || !token) {
    return (
      <Centered>
        <Result
          status="info"
          title="Please sign in to continue"
          extra={
            <Button type="primary" onClick={login}>
              Sign in
            </Button>
          }
        />
      </Centered>
    );
  }

  return (
    <div style={{ height: "100vh" }}>
      {/* Top Header with user info and settings */}
      <Header
        style={{
          background: "transparent",
          padding: "0 16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid #f0f0f0",
          height: "1.75rem",
        }}
      >
        {/* Left side - Settings */}
        <div style={{ width: "20px", display: "flex", alignItems: "center", }}>
          {allowedRoles.includes(selectedRole) && selectedProject?.project_name === "CCM" && <Dropdown overlay={settingsMenu} trigger={["click"]} placement="bottomLeft">
            <SettingOutlined
              style={{
                fontSize: "0.9rem",
                cursor: "pointer",
                color: "#426bba",
              }}
            />
          </Dropdown>}
        </div>

        {/* Right side - User Info */}
        <Space size={4}>
          <Avatar size={12} icon={<UserOutlined style={{ color: "#426bba" }} />} />

          <Text
            style={{
              fontSize: "10px",
              color: "#426bba",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              maxWidth: "120px",
            }}
          >
            {user?.username || user?.name || "User"}
          </Text>
          <LogoutOutlined
            onClick={logout}
            style={{ fontSize: "0.75rem", cursor: "pointer", color: "red" }}
            title="Logout"
          />
        </Space>
      </Header>

      {/* Main content */}
      {/* <Content style={{ padding: 16, overflow: "auto" }}> */}
      <SelectDeliverable email={user.username} />
      {/* </Content> */}
    </div>
  );
};

export default Taskpane;
