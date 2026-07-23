import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import MonitoringTable from "./MonitoringTable";

const MonitoringDialog = () => {
    const [user, setUser] = useState(null);

    const handleClose = () => {
        if (Office.context.ui) {
            Office.context.ui.messageParent(
                JSON.stringify({
                    action: "close",
                })
            );
        }
    };


    useEffect(() => {
        Office.onReady().then(() => {
            Office.context.ui.addHandlerAsync(
                Office.EventType.DialogParentMessageReceived,
                (arg) => {
                    const msg = JSON.parse(arg.message);

                    if (msg.action === "init") {
                        setUser(msg.payload.user);
                    }
                }
            );

            setTimeout(() => {
                Office.context.ui.messageParent(
                    JSON.stringify({
                        action: "ready",
                    })
                );
            }, 100);
        });
    }, []);

    return (
        <div
            style={{
                height: "100vh",
                overflow: "hidden",
            }}
        >
            <MonitoringTable user={user} onClose={handleClose} />
        </div>
    );
};

export default MonitoringDialog;

Office.onReady(() => {
    const container = document.getElementById(
        "monitoring_container"
    );

    if (container) {
        const root = createRoot(container);
        root.render(<MonitoringDialog />);
    } else {
        console.error(
            "#monitoring_container not found"
        );
    }
});