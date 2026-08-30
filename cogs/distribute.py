import discord
from discord.ext import commands
from discord import app_commands
import math

class Distribute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="분배", description="보스 수익 분배 (판매자 수수료 제외 완벽 계산)")
    @app_commands.describe(
        amount="인벤토리에 들어온 총 수령 대금", 
        people="파티 인원 수", 
        percents="(선택) 차등 분배 비율 (맨 앞이 대금을 보유한 판매자). 예: 40 35 25"
    )
    async def split_meso(self, interaction: discord.Interaction, amount: int, people: int, percents: str = None):
        
        if people <= 1:
            return await interaction.response.send_message("⚠️ 인원수는 2명 이상이어야 합니다.", ephemeral=True)

        if not percents:
            # 균등 분배: 총액 / (인원수 - 0.03) 로직
            list_price = math.ceil(amount / (people - 0.03))
            buyer_net = math.floor(list_price * 0.97)
            # 판매자는 나머지 파티원들이 올린 금액을 다 사주고 남은 금액을 가짐
            seller_net = amount - (list_price * (people - 1))
            
            result_text = f"💰 **총 수령 대금:** {amount:,} 메소\n\n"
            
            result_text += f"👑 **판매자 (대금 보유자)**\n"
            result_text += f"🔹 남은 금액(실수령): **{seller_net:,}** 메소 *(경매장 등록 X)*\n\n"
            
            result_text += f"🏷️ **파티원 {people - 1}명 잡템 등록 가격**\n"
            result_text += f"🔹 올려야 할 가격: 인당 **{list_price:,}** 메소\n"
            result_text += f"🔹 (참고) 수수료 뗀 실수령: 인당 {buyer_net:,} 메소"
            
            await interaction.response.send_message(result_text)
            
        else:
            try:
                cleaned_str = percents.replace(",", " ")
                percent_list = [float(p.strip()) for p in cleaned_str.split() if p.strip()]
                
                if len(percent_list) != people:
                    return await interaction.response.send_message(
                        f"⚠️ 인원수({people}명)와 입력한 퍼센트의 개수({len(percent_list)}개)가 일치하지 않습니다!", 
                        ephemeral=True
                    )
                
                total_percent = sum(percent_list)
                if not (99.9 <= total_percent <= 100.1): 
                    return await interaction.response.send_message(
                        f"⚠️ 입력한 퍼센트의 합이 100%가 아닙니다! (현재 합: {total_percent}%)\n비율을 다시 확인해주세요.", 
                        ephemeral=True
                    )
                
                # 맨 앞 배율 = 판매자 (f0), 나머지 배율 = 파티원 (f_rest)
                f0 = percent_list[0] / 100.0
                f_rest = 1.0 - f0
                
                if f_rest <= 0:
                    return await interaction.response.send_message("⚠️ 판매자(첫 번째)의 비율이 100%일 수 없습니다.", ephemeral=True)
                
                # 수수료율을 감안하여 역산한 진정한 가치 풀(Pool)
                v_total = amount / (f0 + (f_rest / 0.97))
                
                buyer_texts = []
                total_listed = 0
                
                # 두 번째 배율(파티원들)부터 잡템 가격 계산
                for idx, p in enumerate(percent_list[1:], start=1):
                    f_i = p / 100.0
                    list_price = math.ceil((v_total * f_i) / 0.97)
                    net_price = math.floor(list_price * 0.97)
                    total_listed += list_price
                    
                    display_p = int(p) if p.is_integer() else p
                    buyer_texts.append(f"🔹 {display_p}%: **{list_price:,}** 메소 *(실수령: {net_price:,})*")
                    
                # 판매자는 총 대금에서 파티원들 물건을 다 사주고 남은 잔액을 가짐
                seller_net = amount - total_listed
                display_p0 = int(percent_list[0]) if percent_list[0].is_integer() else percent_list[0]
                
                result_text = f"💰 **총 수령 대금:** {amount:,} 메소\n\n"
                
                result_text += f"👑 **판매자 ({display_p0}%)**\n"
                result_text += f"🔹 남은 금액(실수령): **{seller_net:,}** 메소 *(경매장 등록 X)*\n\n"
                
                result_text += f"🏷️ **파티원 잡템 등록 가격 (수수료 포함)**\n"
                result_text += "\n".join(buyer_texts)
                    
                await interaction.response.send_message(result_text)
                
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ 퍼센트는 숫자로만 입력해주세요. (예: 40 35 25 또는 40,35,25)", 
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Distribute(bot))