import React, { useState, useEffect } from "react";
import { Table, Tooltip, Button, message, Modal } from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import styled from "styled-components";
import UserEditModal from "./UserEditModal";
import { StyledTableWrapper } from "./UserTableStyles";
import { useRole } from "../../contexts/RoleContext";
import {
  addProjectMember,
  getAllGlobalUsers,
  getAllProjectMemebers,
  getData,
  getProjects,
  removeProjectMember,
  updateProjectMemberRole,
} from "../../../services/ccmApiService";
import { useAuth } from "../../contexts/AuthContext";

const StyledButton = styled(Button)`
  background: #e3ecff;
  color: #426bba !important;
  font-weight: 600;
  font-size: 14px;
  border: none;
  border-radius: 1rem;
  box-shadow: 0 2px 6px rgba(66, 107, 186, 0.2);
  padding: 4px 16px;

  &:hover {
    background: #d7e4ff !important;
    color: #426bba !important;
  }
`;

export const handleApiErrorResponse = (response) => {
  if (!response?.error) {
    return false;
  }

  Modal.error({
    title: "Error",
    content: response.error,
    centered: true,
  });

  return true;
};

const UserTable = () => {
  const [users, setUsers] = useState([]);

  const [globalUsers, setGlobalUsers] = useState([]);
  const [projects, setProjects] = useState([]);

  const [editModalOpen, setEditModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingDropdowns, setLoadingDropdowns] = useState(false);

  const { user } = useAuth();
  const { setUserSelected, selectedProject } = useRole();

  const loadData = async () => {
    try {
      const res = await getData({ action: "get_project_members", email: user?.username, project_id: selectedProject?.project_id });
      const members = res?.members || [];
      setUsers(
        members.map((member) => ({
          ...member,
          application: selectedProject.project_name,
          project_id: selectedProject?.project_id,
        }))
      );
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadDropdownData = async () => {
    try {
      setLoadingDropdowns(true);
      const [usersRes, projectsRes] = await Promise.all([
        getData({
          action: "get_all_users",
          email: user?.username,
          project_id: selectedProject?.project_id
        }),
        getData({ action: "get_all_projects" }),
      ]);

      setGlobalUsers(usersRes?.users || []);
      setProjects(projectsRes?.projects || []);
    } catch (error) {
      console.error("Failed to load dropdown data", error);
    } finally {
      setLoadingDropdowns(false);
    }
  };

  const handleAddUser = async () => {
    setSelectedUser(null);
    setEditModalOpen(true);
  };

  const handleEdit = (record) => {
    setSelectedUser(record);
    setEditModalOpen(true);
  };

  const handleSave = async (values) => {
    try {
      setLoading(true);

      if (selectedUser) {
        const payload = {
          actor_email: user?.username,
          project_id: selectedUser.project_id,
          target_email: selectedUser.email,
          new_role: values.users?.[0]?.assignments?.[0]?.role,
        };

        const res = await updateProjectMemberRole(payload);

        if (handleApiErrorResponse(res)) {
          return;
        }
        message.success("User role updated successfully");

      } else {
        const payloads = values.users.flatMap((userEntry) =>
          userEntry.assignments.map((item) => ({
            actor_email: user?.username,
            project_id: item.application,
            target_email: userEntry.email,
            role: item.role,
          }))
        );

        const res = await addProjectMember({ payload: payloads });

        if (handleApiErrorResponse(res)) {
          return;
        }

        const results = res?.results || []
        console.log("results:", results);

        const failedMessages = [];

        results?.forEach((item) => {
          if (item.status_code === 409) {
            failedMessages.push(item.error);
          }
        });

        if (failedMessages.length) {

          Modal.warning({
            title: "User Already Assigned",
            content: (
              <div>
                {failedMessages.map((msg, idx) => (
                  <div key={idx}>{msg}</div>
                ))}
              </div>
            ),
            afterClose: loadData()
          });
          return;
        }

        message.success("User added successfully");
      }

      await loadData();

      setEditModalOpen(false);
      setSelectedUser(null);
    } catch (error) {
      console.error("Failed to save user", error);
      message.error("Failed to save user");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (record) => {
    console.log("record: ", record);
    try {
      setLoading(true);
      const payload = {
        actor_email: user?.username,
        project_id: selectedProject.project_id,
        target_email: record.email,
      };

      const res = await removeProjectMember(payload);

      if (handleApiErrorResponse(res)) {
        return;
      }

      message.success("User removed successfully");

      setUsers((prev) => prev.filter((user) => user.user_id !== record.user_id));
    } catch (error) {
      console.error("Failed to delete user", error);
      message.error("Failed to delete user");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    loadDropdownData();
  }, []);

  const confirmDelete = (record) => {
    Modal.confirm({
      title: "Remove User",
      content: (
        <div>
          Are you sure you want to remove
          <br />
          <strong>{record.name}</strong> ({record.email})?
        </div>
      ),
      okText: "Remove",
      cancelText: "Cancel",
      okButtonProps: {
        danger: true,
      },
      centered: true,
      onOk: () => handleDelete(record),
    });
  };

  const columns = [
    {
      title: "Name",
      dataIndex: "name",
      width: 100,
    },
    {
      title: "Email",
      dataIndex: "email",
      width: 180,
    },
    {
      title: "Application",
      dataIndex: "application",
      width: 180,
      render: (_, record) => (
        <span>
          {record.application}
          {record.role_name ? ` (${record.role_name})` : ""}
        </span>
      ),
    },
    {
      title: "Action",
      width: 50,
      align: "center",
      render: (_, record) => (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: 12,
          }}
        >
          <Tooltip title="Edit User">
            <EditOutlined className="edit-icon" onClick={() => handleEdit(record)} />
          </Tooltip>

          <Tooltip title="Delete User">
            <DeleteOutlined
              onClick={() => confirmDelete(record)}
              style={{
                cursor: "pointer",
                color: "#ff4d4f",
                fontSize: 14,
              }}
            />
          </Tooltip>
        </div>
      ),
    },
  ];

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          marginTop: "1rem",
          gap: "2rem",
          padding: "0px 8px"
        }}
      >
        <StyledButton type="primary" onClick={() => setUserSelected(false)}>
          Back
        </StyledButton>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginTop: 20,
          marginBottom: 10,
        }}
      >
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleAddUser}
          style={{
            background: "#426bba",
            borderColor: "#426bba",
            fontSize: 12,
            height: 30,
          }}
        >
          Add New User
        </Button>
      </div>

      <StyledTableWrapper>
        <Table
          dataSource={users}
          columns={columns}
          loading={loading}
          pagination={false}
          rowKey="user_id"
          scroll={{
            x: 900,
            y: 300,
          }}
        />
      </StyledTableWrapper>

      <UserEditModal
        open={editModalOpen}
        onClose={() => setEditModalOpen(false)}
        userData={selectedUser}
        onSave={handleSave}
        users={globalUsers}
        projects={projects}
        loading={loadingDropdowns}
        mode={selectedUser ? "edit" : "add"}
        currentUserRole={selectedProject?.role_name}
      />
    </>
  );
};

export default UserTable;
