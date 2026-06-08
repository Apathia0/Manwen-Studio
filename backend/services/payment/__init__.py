# 支付网关注册表

from typing import Any
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult

_gateways: dict[str, PaymentGateway] = {}


def register_gateway(gateway: PaymentGateway) -> None:
    """注册支付网关"""
    _gateways[gateway.method_key] = gateway


def get_gateway(method_key: str) -> PaymentGateway | None:
    """根据 method_key 获取网关实例（支持 provider 前缀回退，如 epay_alipay → epay）"""
    gateway = _gateways.get(method_key)
    if gateway is not None:
        return gateway
    # 按 provider 前缀匹配：epay_alipay → provider="epay"
    for g in _gateways.values():
        if g.provider and method_key.startswith(f"{g.provider}_"):
            return g
    return None


def get_gateway_by_provider(provider: str) -> PaymentGateway | None:
    """根据 provider 获取网关实例"""
    for g in _gateways.values():
        if g.provider == provider:
            return g
    return None


def all_gateways() -> list[PaymentGateway]:
    """获取所有已注册网关"""
    return list(_gateways.values())


def get_method_options(payment_config: dict[str, Any]) -> list[dict[str, Any]]:
    """返回所有已启用的支付方式选项"""
    results = []
    for method_key, gateway in _gateways.items():
        if gateway.provider == "mock":
            continue  # 模拟支付已移除
        enabled_key = f"{gateway.provider}_enabled"
        if not bool(payment_config.get(enabled_key, False)):
            continue

        # 支持网关返回多个动态选项（如易支付每种通道一个选项）
        dynamic_opts = getattr(gateway, "get_type_options", None)
        if dynamic_opts:
            results.extend(dynamic_opts(payment_config))
        else:
            results.append({
                "key": method_key,
                "label": getattr(gateway, "label", method_key),
                "enabled": True,
                "provider": gateway.provider,
            })
    return results


def init_gateways() -> None:
    """初始化所有网关（应用启动时调用）"""
    from .mock_gateway import MockGateway
    from .alipay_gateway import AlipayGateway
    from .epay_gateway import EpayGateway
    from .mapay_gateway import MaPayGateway

    register_gateway(MockGateway())
    register_gateway(AlipayGateway())
    register_gateway(EpayGateway())
    register_gateway(MaPayGateway())


__all__ = [
    "PaymentGateway", "CheckoutResult", "NotifyResult", "StatusSyncResult",
    "register_gateway", "get_gateway", "get_gateway_by_provider", "all_gateways",
    "get_method_options", "init_gateways",
]
