import React, { useEffect } from "react";
import { Modal, Form, Select, Button, Tooltip } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import styled, { createGlobalStyle } from "styled-components";

/* ─── Global ───────────────────────────────────────────────────────── */
const AntCompactGlobal = createGlobalStyle`
  .compact-modal-dropdown {
    min-width: 0 !important;
  }
  .compact-modal-dropdown .ant-select-item {
    font-size: 11px !important;
    padding: 5px 10px !important;
    min-height: 28px !important;
    line-height: 18px !important;
  }
  .compact-modal-dropdown .ant-select-item-option-content {
    font-size: 11px !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
`;

const ModalWrapper = styled.div`
  .ant-form-item-label > label {
    font-size: 11px !important;
    font-weight: 600;
    color: #374151;
    height: 20px;
  }
  .ant-form-item {
    margin-bottom: 8px;
  }
  .ant-select {
    width: 100%;
    min-width: 0;
  }
  .ant-select .ant-select-selector {
    height: 28px !important;
    min-height: 28px !important;
    max-height: 28px !important;
    padding: 0 24px 0 8px !important;
    border-radius: 6px !important;
    border: 1px solid #d1d5db !important;
    background: #f9fafb !important;
    display: flex !important;
    align-items: center !important;
    overflow: hidden !important;
  }
  .ant-select .ant-select-selection-search {
    height: 26px !important;
    line-height: 26px !important;
    inset-inline-start: 8px !important;
    inset-inline-end: 24px !important;
  }
  .ant-select .ant-select-selection-search-input {
    height: 26px !important;
    font-size: 11px !important;
  }
  .ant-select .ant-select-selection-item {
    font-size: 11px !important;
    line-height: 26px !important;
    height: 26px !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    display: block !important;
    padding-inline-end: 0 !important;
    min-width: 0 !important;
  }
  .ant-select .ant-select-selection-placeholder {
    font-size: 11px !important;
    line-height: 26px !important;
    color: #9ca3af !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
  }
  .ant-select .ant-select-arrow {
    font-size: 10px;
    color: #9ca3af;
    inset-inline-end: 7px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    margin-top: 0 !important;
  }
  .ant-select:not(.ant-select-disabled):hover .ant-select-selector,
  .ant-select-focused:not(.ant-select-disabled) .ant-select-selector {
    border-color: #426bba !important;
    box-shadow: 0 0 0 2px rgba(66, 107, 186, 0.1) !important;
    background: #fff !important;
  }
  .ant-select-disabled .ant-select-selector {
    background: #f3f4f6 !important;
    color: #6b7280 !important;
    cursor: not-allowed !important;
  }
  .ant-form-item-has-error .ant-select .ant-select-selector {
    border-color: #ff4d4f !important;
  }
`;

/* ─── Styled ─────────────────────────────────────────────────────────── */
const SectionTitle = styled.p`
  font-size: 11px;
  font-weight: 700;
  color: #111827;
  margin: 4px 0 6px;
  letter-spacing: 0.02em;
`;

// Outer user block
const UserBlock = styled.div`
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #fff;
`;

// User row: email select + delete user icon
const UserRow = styled.div`
  display: grid;
  grid-template-columns: 1fr 20px;
  gap: 6px;
  align-items: center;
  min-width: 0;
  .ant-form-item {
    margin-bottom: 6px !important;
    min-width: 0;
  }
`;

// App + Role row: 35% app | 65% role | delete icon | add icon
const AppRoleRow = styled.div`
  display: grid;
  grid-template-columns: 35fr 65fr 16px;
  gap: 6px;
  align-items: center;
  margin-bottom: 4px;
  min-width: 0;
  .ant-form-item {
    margin-bottom: 0 !important;
    min-width: 0;
  }
`;

const IconBtn = styled.span`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  flex-shrink: 0;
  font-size: 13px;

  cursor: ${({ disabled }) => (disabled ? "not-allowed" : "pointer")};
  color: ${({ disabled }) => (disabled ? "#d1d5db" : "#426bba")};

  pointer-events: ${({ disabled }) => (disabled ? "none" : "auto")};

  &:hover {
    color: ${({ disabled, $danger }) =>
    disabled ? "#d1d5db" : $danger ? "#ff4d4f" : "#426bba"};
  }
`;

const AddUserBtn = styled(Button)`
  && {
    width: 100%;
    height: 28px;
    font-size: 11px;
    font-weight: 600;
    color: #426bba;
    border: 1.5px dashed #bfcfe8;
    border-radius: 6px;
    background: transparent;
    margin-top: 2px;
    margin-bottom: 14px;

    &:hover {
      background: #f0f5ff !important;
      border-color: #426bba !important;
      color: #426bba !important;
    }
  }
`;

const FooterRow = styled.div`
  display: flex;
  justify-content: flex-end;
  gap: 8px;
`;

/* ─── Constants ─────────────────────────────────────────────────────── */
const ROLE_MAP = {
  4: "SUPER_ADMIN", 
  1: "SYSTEM_SUPPORT_ADMIN",
  2: "BUSINESS_ADMIN",
  3: "WRITER",
};

/* ─── Component ─────────────────────────────────────────────────────── */
const UserEditModal = ({
  open,
  onClose,
  userData,
  onSave,
  users = [],
  projects = [],
  loading = false,
  mode = "add",
  currentUserRole,
}) => {
  const [form] = Form.useForm();
  const isEdit = mode === "edit";

  const ROLE_OPTIONS = Object.entries(ROLE_MAP)
  .filter(([, label]) => {
    if (label === "SUPER_ADMIN" && currentUserRole !== "SUPER_ADMIN") return false;
    if (label === "SYSTEM_SUPPORT_ADMIN" && currentUserRole === "BUSINESS_ADMIN") return false;
    return true;
  })
  .map(([value, label]) => ({ value, label }));

  const userOptions = users.map((u) => ({
    label: `${u.name} (${u.email})`,
    value: u.email,
  }));

  const applicationOptions = projects.filter((p) => p.project_name === "CCM").map((p) => ({
    label: p.project_name,
    value: String(p.project_id),
  }));

  const resolveRoleValue = (role) => {
    if (!role) return undefined;
    if (ROLE_MAP[role] || ROLE_MAP[String(role)]) return String(role);
    const entry = Object.entries(ROLE_MAP).find(([, v]) => v === role);
    return entry ? entry[0] : undefined;
  };

  useEffect(() => {
    if (!open) return;
    if (userData) {
      form.setFieldsValue({
        users: [
          {
            email: userData.email,
            assignments: [
              {
                application: userData.project_id != null ? String(userData.project_id) : undefined,
                role: resolveRoleValue(userData.role ?? userData.role_name),
              },
            ],
          },
        ],
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        users: [{ email: undefined, assignments: [{ application: undefined, role: undefined }] }],
      });
    }
  }, [open, userData]);

  const handleSubmit = async () => {
    const values = await form.validateFields();
    onSave(values);
    onClose();
  };

  const selectProps = {
    popupClassName: "compact-modal-dropdown",
    style: { width: "100%" },
  };

  return (
    <>
      <AntCompactGlobal />
      <Modal
        open={open}
        title={
          <span style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>
            {isEdit ? "Edit User" : "Add User"}
          </span>
        }
        onCancel={onClose}
        footer={null}
        centered
        width={380}
        destroyOnClose
        styles={{
          header: { padding: "12px 16px 10px", borderBottom: "1px solid #f0f0f0" },
          body: { padding: "12px 16px 4px" },
        }}
      >
        <ModalWrapper>
          <Form form={form} layout="vertical" requiredMark={false}>
            <SectionTitle>Users &amp; Application Roles</SectionTitle>

            {/* ── Outer: list of users ─────────────────────── */}
            <Form.List
              name="users"
              initialValue={[{ email: undefined, assignments: [{ application: undefined, role: undefined }] }]}
            >
              {(userFields, { add: addUser, remove: removeUser }) => (
                <>
                  {userFields.map(({ key: uKey, name: uName, ...uRest }) => {

                    const usersData = form.getFieldValue("users") || []
                    const selectedEmails = usersData.map(u => u?.email).filter(Boolean)

                    return (
                      <UserBlock key={uKey}>
                        {/* User row */}
                        <UserRow>
                          <Form.Item
                            {...uRest}
                            name={[uName, "email"]}
                            rules={[{ required: true, message: "Select a user" }]}
                          >
                            <Select
                              {...selectProps}
                              showSearch
                              placeholder="Select user…"
                              // options={userOptions}
                              disabled={isEdit}
                              loading={loading}
                              optionFilterProp="label"
                              options={userOptions.map((user) => ({
                                ...user,
                                disabled:
                                  selectedEmails.includes(user.value) &&
                                  usersData[uName]?.email !== user.value,
                              }))}
                            />
                          </Form.Item>

                          {/* Delete entire user block */}
                          {userFields.length > 1 ? (
                            <Tooltip title="Remove user">
                              <IconBtn $danger onClick={() => removeUser(uName)}>
                                <DeleteOutlined />
                              </IconBtn>
                            </Tooltip>
                          ) : (
                            <span style={{ width: 16 }} />
                          )}
                        </UserRow>

                        {/* Inner: app + role rows for this user */}
                        <Form.List
                          name={[uName, "assignments"]}
                          initialValue={[{ application: undefined, role: undefined }]}
                        >
                          {(appFields, { add: addApp, remove: removeApp }) => (
                            <>
                              {appFields.map(({ key: aKey, name: aName, ...aRest }, appIndex) => {
                                const isLastApp = appIndex === appFields.length - 1;

                                return (
                                  <AppRoleRow key={aKey}>
                                    <Form.Item {...aRest} name={[aName, "application"]} rules={[{ required: true, message: "" }]}>
                                      <Select {...selectProps} placeholder="App" options={applicationOptions} disabled={isEdit} loading={loading} />
                                    </Form.Item>

                                    <Form.Item {...aRest} name={[aName, "role"]} rules={[{ required: true, message: "" }]}>
                                      <Select {...selectProps} placeholder="Role" options={ROLE_OPTIONS} loading={loading} />
                                    </Form.Item>

                                    {/* Single icon slot: + on last row, delete on all others */}
                                    {isLastApp ? (
                                      <Tooltip title="Add app">
                                        <IconBtn onClick={() => addApp({ application: undefined, role: undefined })} disabled={true}>
                                          <PlusOutlined />
                                        </IconBtn>
                                      </Tooltip>
                                    ) : (
                                      <Tooltip title="Remove app">
                                        <IconBtn $danger onClick={() => removeApp(aName)}>
                                          <DeleteOutlined />
                                        </IconBtn>
                                      </Tooltip>
                                    )}
                                  </AppRoleRow>
                                );
                              })}
                            </>
                          )}
                        </Form.List>
                      </UserBlock>
                    )
                  })}

                  {/* Add another user block — hidden in edit mode */}
                  {!isEdit && (
                    <AddUserBtn
                      type="dashed"
                      icon={<PlusOutlined style={{ fontSize: 10 }} />}
                      onClick={() =>
                        addUser({ email: undefined, assignments: [{ application: undefined, role: undefined }] })
                      }
                    >
                      Add User
                    </AddUserBtn>
                  )}
                </>
              )}
            </Form.List>

            {/* ── Footer ────────────────────────────────────── */}
            <FooterRow>
              <Button onClick={onClose} style={{ fontSize: 12, height: 30, borderRadius: 6 }}>
                Cancel
              </Button>
              <Button
                type="primary"
                onClick={handleSubmit}
                style={{
                  fontSize: 12,
                  height: 30,
                  borderRadius: 6,
                  background: "#426bba",
                  borderColor: "#426bba",
                  fontWeight: 600,
                }}
              >
                {isEdit ? "Save" : "Add User"}
              </Button>
            </FooterRow>
          </Form>
        </ModalWrapper>
      </Modal>
    </>
  );
};

export default UserEditModal;