// antd 5's static methods (message.success(...), notification.*, Modal.confirm)
// rendered through ReactDOM.render, which React 19 removed. This official patch
// swaps in a createRoot-based renderer. It must load before any such call, so
// main.tsx imports it first; the tests import it too and fail without it.
import "@ant-design/v5-patch-for-react-19";
