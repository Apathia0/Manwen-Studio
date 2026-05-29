import { ref } from 'vue'
import { billingApi } from '@/api'

export function usePayment() {
  const loading = ref(false)

  /* 返回当前平台对应的支付方式 key。H5 固定传 mock_qr，不依赖后端 default_method */
  function getPaymentMethod(): string {
    // #ifdef MP-WEIXIN
    return 'wechat_jsapi'
    // #endif
    // #ifdef APP-PLUS
    return 'wechat_app'
    // #endif
    // #ifndef MP-WEIXIN || APP-PLUS
    return 'mock_qr'
    // #endif
  }

  async function subscribe(planId: number, cycle: string): Promise<any> {
    loading.value = true
    try {
      /* 先用平台对应的支付方式（H5=mock_qr, MP=wechat_jsapi, APP=wechat_app） */
      let method = getPaymentMethod()
      try {
        return await billingApi.subscribe(planId, cycle, method)
      } catch (e1: any) {
        /* mock_qr 不可用时（mock_enabled=false），改用后端 default_method */
        if (e1.message?.includes('Payment method unavailable') && method === 'mock_qr') {
          method = ''
        } else {
          throw e1
        }
      }
      return await billingApi.subscribe(planId, cycle, method)
    } finally {
      loading.value = false
    }
  }

  async function mockConfirm(orderNo: string) {
    return await billingApi.mockConfirm(orderNo)
  }

  async function syncOrder(orderNo: string) {
    return await billingApi.syncOrder(orderNo)
  }

  async function payWithWechatMP(prepay: any): Promise<boolean> {
    return new Promise((resolve) => {
      // #ifdef MP-WEIXIN
      ;(uni as any).requestPayment({
        ...prepay,
        success: () => resolve(true),
        fail: (err: any) => {
          if (err.errMsg !== 'requestPayment:fail cancel') {
            uni.showToast({ title: '支付失败', icon: 'none' })
          }
          resolve(false)
        }
      })
      // #endif
      // #ifndef MP-WEIXIN
      resolve(false)
      uni.showToast({ title: '当前环境不支持微信支付', icon: 'none' })
      // #endif
    })
  }

  async function payWithApp(provider: string, orderInfo: any): Promise<boolean> {
    return new Promise((resolve) => {
      // #ifdef APP-PLUS
      uni.requestPayment({
        provider: provider as any,
        orderInfo,
        success: () => resolve(true),
        fail: (err: any) => {
          if (err.errMsg !== 'requestPayment:fail cancel') {
            uni.showToast({ title: '支付失败', icon: 'none' })
          }
          resolve(false)
        }
      })
      // #endif
      // #ifndef APP-PLUS
      resolve(false)
      uni.showToast({ title: '当前环境不支持原生支付', icon: 'none' })
      // #endif
    })
  }

  async function pollOrderStatus(orderNo: string): Promise<boolean> {
    for (let i = 0; i < 30; i++) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      try {
        const result = await billingApi.syncOrder(orderNo)
        if (result?.status === 'paid' || result?.status === 'confirmed') {
          return true
        }
        if (result?.status === 'cancelled' || result?.status === 'expired') {
          return false
        }
      } catch (e) {
        console.error('轮询订单状态失败:', e)
      }
    }
    return false
  }

  return {
    loading,
    subscribe,
    mockConfirm,
    syncOrder,
    payWithWechatMP,
    payWithApp,
    pollOrderStatus
  }
}
