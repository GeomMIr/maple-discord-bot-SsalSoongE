import discord
from discord.ext import commands
from discord import app_commands
import math

class Distribute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="분배", description="보스 수익금을 분배합니다. (독박 수수료 방지 적용)")
    @app_commands.describe(
        amount="정산 대상 총 금액 (인벤토리에 들어온 총 수령 대금)", 
        people="파티 인원 수", 
        percents="(선택) 차등 분배 시 퍼센트를 띄어쓰기나 쉼표로 입력 (예: 40 35 25)"
    )
    async def split_meso(self, interaction: discord.Interaction, amount: int, people: int, percents: str = None):
        
        if people <= 1:
            return await interaction.response.send_message("⚠️ 인원수는 2명 이상이어야 합니다.", ephemeral=True)

        if not percents:
            # 1/N 균등 분배 로직: P = T / (N - 0.03)
            list_price = math.ceil(amount / (people - 0.03))
            net_price = math.floor(list_price * 0.97)
            
            result_text = f"📥 **분배 금액 (실수령액)**\n"
            result_text += f"🔹 {people}명 균등: 인당 **{net_price:,}** 메소\n\n"
            
            result_text += f"🏷️ **올려야 하는 잡템 가격 (수수료 포함)**\n"
            result_text += f"🔹 1인당: **{list_price:,}** 메소"
            
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
                
                # 비율 분배 로직: 판매자가 누군지 특정할 수 없으므로 평균 수수료 분담 풀(Pool) 생성
                base_pool = amount / (1 - (0.03 / people))
                
                net_text = "📥 **분배 금액 (실수령액)**\n"
                list_text = "🏷️ **올려야 하는 잡템 가격 (수수료 포함)**\n"
                
                for p in percent_list:
                    list_price = math.ceil(base_pool * (p / 100))
                    net_price = math.floor(list_price * 0.97)
                    
                    display_p = int(p) if p.is_integer() else p
                    net_text += f"🔹 {display_p}% - **{net_price:,}** 메소\n"
                    list_text += f"🔹 {display_p}% - **{list_price:,}** 메소\n"
                    
                result_text = net_text + "\n" + list_text
                    
                await interaction.response.send_message(result_text)
                
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ 퍼센트는 숫자로만 입력해주세요. (예: 40 35 25 또는 40,35,25)", 
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Distribute(bot))